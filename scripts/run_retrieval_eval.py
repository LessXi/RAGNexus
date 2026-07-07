"""RAGNexus 检索评估脚本 — 基于 RAGAS 的 context_precision + context_recall。

逐条调用 POST /v1/rag:retrieve，使用 RAGAS 计算检索质量指标，输出 JSON 报告。

用法:
    uv run python scripts/run_retrieval_eval.py \
        --dataset eval/datasets/_seed_ecommerce.json \
        --kb-ids kb_xxxxxxxx \
        --api-key sk-xxx \
        --base-url http://localhost:8000 \
        --profile balanced \
        --output eval/reports/report.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

import httpx
from datasets import Dataset
from ragas import evaluate
from ragas.metrics.collections import context_precision, context_recall

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="RAGNexus 检索管线 RAGAS 评估",
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path("eval/datasets/_seed_ecommerce.json"),
        help="golden set JSON 路径 (default: eval/datasets/_seed_ecommerce.json)",
    )
    parser.add_argument(
        "--api-key",
        required=True,
        help="API Key",
    )
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="API 基础地址 (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--profile",
        default="balanced",
        choices=["speed", "balanced", "quality", "custom"],
        help="检索 profile (default: balanced)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("eval/reports/report.json"),
        help="报告输出路径 (default: eval/reports/report.json)",
    )
    parser.add_argument(
        "--kb-ids",
        required=True,
        nargs="+",
        help="知识库 ID 列表 (必填，至少一个)",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="检索返回数 (default: 5)",
    )
    return parser.parse_args()


async def retrieve(
    client: httpx.AsyncClient,
    base_url: str,
    api_key: str,
    query: str,
    kb_ids: list[str],
    profile: str,
    top_k: int,
) -> list[str]:
    """调用 POST /v1/rag:retrieve，返回检索到的文本列表。"""
    url = f"{base_url.rstrip('/')}/v1/rag:retrieve"
    payload = {
        "query": query,
        "kb_ids": kb_ids,
        "top_k": top_k,
        "profile": profile,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    resp = await client.post(url, json=payload, headers=headers)
    resp.raise_for_status()
    body = resp.json()

    # API 返回格式: {"code": 0, "data": {"hits": [...], "meta": {...}}}
    data = body.get("data", {})
    hits = data.get("hits", [])
    return [hit.get("text", "") for hit in hits]


async def run_eval(args: argparse.Namespace) -> dict:
    """主评估流程：读数据集 → 逐条检索 → RAGAS 评估 → 输出报告。"""
    # 1. 读 golden set
    dataset_path = args.dataset
    if not dataset_path.exists():
        logger.error("数据集文件不存在: %s", dataset_path)
        sys.exit(1)

    golden = json.loads(dataset_path.read_text(encoding="utf-8"))
    logger.info("加载 golden set: %s (%d 条)", dataset_path, len(golden))

    # 2. 逐条检索 + 构建 RAGAS Dataset
    questions: list[str] = []
    contexts_list: list[list[str]] = []
    ground_truths: list[str] = []
    skipped: list[dict] = []
    low_recall_cases: list[dict] = []

    async with httpx.AsyncClient(timeout=30.0) as client:
        for i, item in enumerate(golden):
            question = item.get("question", "")
            ground_truth = item.get("ground_truth", "")

            if not question:
                logger.warning("[%d] 跳过: question 为空", i)
                skipped.append({"index": i, "reason": "question 为空"})
                continue

            if not ground_truth:
                logger.warning('[%d] 跳过: ground_truth 为空 — "%s"', i, question)
                skipped.append({"index": i, "question": question, "reason": "ground_truth 为空"})
                continue

            try:
                contexts = await retrieve(
                    client,
                    args.base_url,
                    args.api_key,
                    question,
                    args.kb_ids,
                    args.profile,
                    args.top_k,
                )
            except httpx.HTTPStatusError as e:
                logger.error('[%d] HTTP %d — "%s": %s', i, e.response.status_code, question, e)
                skipped.append(
                    {
                        "index": i,
                        "question": question,
                        "reason": f"HTTP {e.response.status_code}",
                    }
                )
                continue
            except Exception as e:
                logger.error('[%d] 请求失败 — "%s": %s', i, question, e)
                skipped.append(
                    {
                        "index": i,
                        "question": question,
                        "reason": str(e),
                    }
                )
                continue

            if not contexts:
                logger.warning('[%d] 检索无结果 — "%s"', i, question)

            questions.append(question)
            contexts_list.append(contexts)
            ground_truths.append(ground_truth)
            logger.info('[%d] ✓ "%s" → %d chunks', i, question, len(contexts))

    # 3. 无有效条目时直接退出
    if not questions:
        logger.error("无有效评估条目 (所有条目 ground_truth 为空或请求失败)")
        report = {
            "metrics": {},
            "low_recall_cases": [],
            "skipped": skipped,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("报告已输出: %s", args.output)
        return report

    # 4. RAGAS 评估
    logger.info("开始 RAGAS 评估 (%d 条有效)", len(questions))
    ragas_dataset = Dataset.from_dict(
        {
            "question": questions,
            "contexts": contexts_list,
            "ground_truth": ground_truths,
        }
    )

    result = evaluate(
        ragas_dataset,
        metrics=[context_precision, context_recall],
    )

    # 5. 提取指标
    metrics: dict = {}
    if hasattr(result, "to_pandas"):
        df = result.to_pandas()
        for col in ["context_precision", "context_recall"]:
            if col in df.columns:
                series = df[col].dropna()
                if not series.empty:
                    metrics[col] = round(float(series.mean()), 4)
                else:
                    metrics[col] = None
    else:
        # fallback: result 可能是 dict
        metrics = {k: round(float(v), 4) for k, v in result.items() if isinstance(v, (int, float))}

    # 6. context_recall 偏低 case 单独列出
    recall_threshold = 0.5
    if hasattr(result, "to_pandas"):
        df = result.to_pandas()
        if "context_recall" in df.columns:
            for idx, row in df.iterrows():
                cr = row.get("context_recall")
                if cr is not None and float(cr) < recall_threshold:
                    low_recall_cases.append(
                        {
                            "question": questions[idx],
                            "context_recall": round(float(cr), 4),
                            "contexts": contexts_list[idx],
                            "ground_truth": ground_truths[idx],
                        }
                    )

    # 7. 输出报告
    report = {
        "metrics": metrics,
        "low_recall_cases": low_recall_cases,
        "skipped": skipped,
        "summary": {
            "total": len(golden),
            "evaluated": len(questions),
            "skipped": len(skipped),
        },
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("报告已输出: %s", args.output)

    # 终端摘要
    print(
        json.dumps(
            {
                "metrics": metrics,
                "evaluated": len(questions),
                "low_recall_count": len(low_recall_cases),
            },
            ensure_ascii=False,
            indent=2,
        )
    )

    return report


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    args = parse_args()
    asyncio.run(run_eval(args))


if __name__ == "__main__":
    main()
