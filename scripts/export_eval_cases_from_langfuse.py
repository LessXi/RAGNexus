"""从 Langfuse 拉取低分反馈，导出为评测 golden set JSON。

用法：
    uv run python scripts/export_eval_cases_from_langfuse.py \\
        --max-score 3 --days 30

输出 JSON 格式：[{"question": "...", "ground_truth": ""}]

配置通过环境变量 LANGFUSE_HOST / LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY 传入。
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

# Langfuse 公开 API 路由（相对于 base_url）
_SCORES_PATH = "/api/public/scores"
_TRACES_PATH = "/api/public/traces"
_PAGE_SIZE = 50


def _build_client() -> httpx.Client:
    """从环境变量读取 Langfuse 配置，构建带 Basic Auth 的 httpx Client。

    配置项：
        LANGFUSE_HOST      — Langfuse 服务地址（如 https://cloud.langfuse.com）
        LANGFUSE_PUBLIC_KEY — 项目 public key
        LANGFUSE_SECRET_KEY — 项目 secret key
    """
    host = os.environ.get("LANGFUSE_HOST", "").rstrip("/")
    public_key = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
    secret_key = os.environ.get("LANGFUSE_SECRET_KEY", "")

    if not host or not public_key or not secret_key:
        print(
            "错误：缺少 Langfuse 配置。"
            "请设置环境变量 LANGFUSE_HOST、LANGFUSE_PUBLIC_KEY、LANGFUSE_SECRET_KEY",
            file=sys.stderr,
        )
        sys.exit(1)
    raw = f"{public_key}:{secret_key}".encode()
    credentials = base64.b64encode(raw).decode()
    return httpx.Client(
        base_url=host,
        headers={"Authorization": f"Basic {credentials}"},
        trust_env=False,
        timeout=30.0,
    )


def _to_numeric(value: object) -> float:
    """安全地将 score value 转为数值，无法转换时返回极大值（不满足 ≤ max_score）。"""
    if value is None:
        return float("inf")
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except (ValueError, TypeError):
        return float("inf")


def _fetch_scores(
    client: httpx.Client,
    max_score: int,
    days: int,
) -> list[dict]:
    """分页拉取 score ≤ max_score 的反馈记录（回溯 days 天）。

    由于 Langfuse 公开 API 不支持 value_lte 查询参数，先按时间窗口拉取全量，
    再在客户端按 score 值过滤。
    """
    since = datetime.now(timezone.utc) - timedelta(days=days)  # noqa: UP017
    params: dict = {
        "fromTimestamp": since.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "limit": _PAGE_SIZE,
        "page": 1,
    }

    all_scores: list[dict] = []
    while True:
        resp = client.get(_SCORES_PATH, params=params)
        resp.raise_for_status()
        data = resp.json()
        items: list[dict] = data.get("data", [])
        if not items:
            break

        # 客户端过滤 score ≤ max_score（仅保留数值型分数）
        filtered = [
            s
            for s in items
            if s.get("dataType") == "NUMERIC"
            and _to_numeric(s.get("value")) <= max_score
        ]
        all_scores.extend(filtered)

        meta = data.get("meta", {})
        total_pages = meta.get("totalPages", 0)
        if meta.get("page", 0) >= total_pages or len(items) < _PAGE_SIZE:
            break
        params["page"] += 1

    return all_scores


def _fetch_trace(client: httpx.Client, trace_id: str) -> dict | None:
    """获取 trace 详情；返回 None 表示 404（trace 可能已被删除）。"""
    try:
        resp = client.get(f"{_TRACES_PATH}/{trace_id}")
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return None
        raise


def _extract_question(trace: dict) -> str | None:
    """从 trace 中提取用户原始查询。

    优先从 metadata.search_query 读取（与现有应用行为一致），
    再尝试 trace.input 作为兜底路径。
    """
    # 主路径：metadata.search_query（retrieve_router 写入的字段）
    metadata = trace.get("metadata")
    if isinstance(metadata, dict):
        sq = metadata.get("search_query")
        if sq and isinstance(sq, str) and sq.strip():
            return sq.strip()

    # 兜底路径：trace.input（其他可能的入库路径）
    input_data = trace.get("input")
    if input_data is None:
        return None

    if isinstance(input_data, str):
        try:
            parsed = json.loads(input_data)
        except (json.JSONDecodeError, TypeError):
            return input_data.strip() or None
        if isinstance(parsed, dict):
            return (
                parsed.get("query")
                or parsed.get("search_query")
                or parsed.get("question")
            )
        return str(parsed) if parsed else None

    if isinstance(input_data, dict):
        return (
            input_data.get("query")
            or input_data.get("search_query")
            or input_data.get("question")
        )
    return str(input_data).strip() or None


def _extract_kb_ids(trace: dict) -> list[str]:
    """从 trace.metadata 中提取 kb_ids 列表，优先 kb_ids 回退 kb_id。"""
    metadata = trace.get("metadata")
    if isinstance(metadata, dict):
        kb_ids = metadata.get("kb_ids", [])
        if isinstance(kb_ids, list) and kb_ids:
            return [str(k) for k in kb_ids]
        if isinstance(kb_ids, str):
            return [kb_ids]

        # 回退：旧 trace 可能只有 kb_id 单库字段
        kb_id = metadata.get("kb_id")
        if kb_id and isinstance(kb_id, str):
            return [kb_id]
    return []


def _load_existing(path: Path) -> list[dict]:
    """加载已有 golden set JSON 文件，不存在时返回空列表。"""
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="从 Langfuse 拉取低分反馈，导出为评测 golden set JSON"
    )
    parser.add_argument(
        "--max-score",
        type=int,
        default=3,
        help="最高分阈值（拉取 score ≤ 此值的反馈），默认 3",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="回溯天数，默认 30",
    )
    parser.add_argument(
        "--kb-id",
        type=str,
        help="按知识库 ID 过滤（可选），仅保留 trace.metadata.kb_ids 包含此 ID 的记录",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="eval/datasets/exported_cases.json",
        help="输出文件路径，默认 eval/datasets/exported_cases.json",
    )
    parser.add_argument(
        "--merge",
        action="store_true",
        default=False,
        help="按 question 去重，与已有 golden set 合并（而非覆盖）",
    )
    args = parser.parse_args()

    # ---- 构建客户端 ----
    client = _build_client()

    try:
        # ---- 1. 拉取低分反馈 ----
        print(f"正在拉取 score ≤ {args.max_score} 的反馈（回溯 {args.days} 天）…")
        scores = _fetch_scores(client, args.max_score, args.days)

        if not scores:
            print("未找到符合条件的反馈。")
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            existing = _load_existing(output_path) if args.merge else []
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(existing, f, ensure_ascii=False, indent=2)
            print(f"已输出到 {output_path}")
            return

        # ---- 2. 关联 trace，提取 question ----
        print(f"找到 {len(scores)} 条低分反馈，正在通过 trace_id 关联 trace…")

        cases: list[dict] = []
        seen_trace_ids: set[str] = set()

        for score in scores:
            trace_id = score.get("traceId")
            if not trace_id or trace_id in seen_trace_ids:
                continue
            seen_trace_ids.add(trace_id)

            trace = _fetch_trace(client, trace_id)
            if trace is None:
                continue

            # kb_id 过滤（可选）
            if args.kb_id:
                kb_ids = _extract_kb_ids(trace)
                if args.kb_id not in kb_ids:
                    continue

            question = _extract_question(trace)
            if question:
                kb_ids = _extract_kb_ids(trace)
                case_entry: dict = {"question": question, "ground_truth": ""}
                if kb_ids:
                    case_entry["kb_ids"] = kb_ids
                cases.append(case_entry)

        print(f"提取到 {len(cases)} 条有效 case（去重 trace 后）。")

        # ---- 3. 输出 ----
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if args.merge:
            existing = _load_existing(output_path)
            existing_questions = {c["question"] for c in existing}
            new_count = 0
            for c in cases:
                if c["question"] not in existing_questions:
                    existing.append(c)
                    existing_questions.add(c["question"])
                    new_count += 1
            print(f"合并模式：新增 {new_count} 条，总计 {len(existing)} 条。")
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(existing, f, ensure_ascii=False, indent=2)
        else:
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(cases, f, ensure_ascii=False, indent=2)

        print(f"已输出到 {output_path}")

    except httpx.ConnectError:
        print(
            "错误：无法连接到 Langfuse 服务，请检查 LANGFUSE_HOST 配置。",
            file=sys.stderr,
        )
        sys.exit(1)
    except httpx.HTTPStatusError as e:
        print(
            f"错误：Langfuse API 返回 {e.response.status_code}。",
            file=sys.stderr,
        )
        sys.exit(1)
    finally:
        client.close()


if __name__ == "__main__":
    main()
