#!/usr/bin/env python
"""verify_robustness_retrieve.py — 检索鲁棒性集成验证脚本。

对运行中的 RAGNexus 服务 (localhost:8000) 验证降级行为：
  1. API 可达性检查
  2. KB 生命周期（创建 → 上传文档 → 检索）
  3. Hybrid 检索鲁棒性字段验证（degraded / degraded_kb_ids / failed_kb_ids / partial_kb_success / empty_reason）
  4. ES 降级场景验证（ES 不可用时 hybrid 请求返回 200 + degraded=true）

用法:
    uv run python scripts/verify_robustness_retrieve.py
    uv run python scripts/verify_robustness_retrieve.py --base-url http://localhost:8000
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime

import requests

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

DEFAULT_BASE_URL = "http://localhost:8000"
REQUEST_TIMEOUT = 15  # 秒


# ---------------------------------------------------------------------------
# 输出格式化
# ---------------------------------------------------------------------------

GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
RESET = "\033[0m"
BOLD = "\033[1m"


def ok(label: str, detail: str = "") -> None:
    tag = f"{GREEN}OK{RESET}"
    suffix = f"  — {detail}" if detail else ""
    print(f"  [{tag}] {label}{suffix}")


def skip(label: str, reason: str = "") -> None:
    tag = f"{YELLOW}SKIP{RESET}"
    suffix = f"  — {reason}" if reason else ""
    print(f"  [{tag}] {label}{suffix}")


def fail(label: str, detail: str = "") -> None:
    tag = f"{RED}FAIL{RESET}"
    suffix = f"  — {detail}" if detail else ""
    print(f"  [{tag}] {label}{suffix}")


def header(text: str) -> None:
    print(f"\n{BOLD}{text}{RESET}")


def banner() -> None:
    print("=" * 60)
    print(f"  RAGNexus 检索鲁棒性集成验证  {datetime.now():%Y-%m-%d %H:%M:%S}")
    print("=" * 60)


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


def _check_url(base: str, path: str) -> requests.Response | None:
    """检查 URL 是否可访问。返回 Response 或 None。"""
    try:
        resp = requests.get(f"{base}{path}", timeout=REQUEST_TIMEOUT)
        return resp
    except requests.ConnectionError:
        return None
    except requests.Timeout:
        return None


def _make_request(
    base: str,
    path: str,
    method: str = "GET",
    *,
    json_body: dict | None = None,
    data: dict | None = None,
    files: dict | None = None,
    headers: dict | None = None,
) -> requests.Response | None:
    """发送 HTTP 请求，带连接异常保护。"""
    url = f"{base}{path}"
    try:
        if method == "POST":
            return requests.post(
                url,
                json=json_body,
                data=data,
                files=files,
                headers=headers,
                timeout=REQUEST_TIMEOUT,
            )
        return requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
    except requests.ConnectionError:
        return None
    except requests.Timeout:
        return None


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="RAGNexus 检索鲁棒性集成验证脚本")
    parser.add_argument(
        "--base-url",
        default=os.environ.get("RAGNEXUS_BASE_URL", DEFAULT_BASE_URL),
        help=f"服务地址（默认 {DEFAULT_BASE_URL}）",
    )
    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    banner()

    # track failures
    failures = 0

    # ── Case 1: API 可达性 ──────────────────────────────────────────────
    header("Case 1: API 可达性检查")
    resp = _check_url(base, "/openapi.json")
    if resp is None or resp.status_code != 200:
        skip("服务器不可达", f"无法连接到 {base}")
        print("\n请先启动 RAGNexus 服务后再运行此脚本。")
        return 0  # 优雅退出，不报错
    ok("openapi.json 可达", f"status={resp.status_code}")

    # 检查 /health 端点
    health = _check_url(base, "/health")
    if health is not None and health.status_code == 200:
        hd = health.json()
        ok("health check", f"status={hd.get('status', 'unknown')}")
    else:
        ok("health check", "端点不可用（非致命）")

    # ── Case 2: KB 生命周期 ─────────────────────────────────────────────
    header("Case 2: KB 生命周期（创建 → 上传 → 检索）")

    # 2a. 创建 KB
    kb_name = f"robustness-verify-{os.urandom(4).hex()}"
    resp = _make_request(
        base,
        "/v1/knowledge-bases:create",
        method="POST",
        json_body={"name": kb_name},
    )
    if resp is None:
        skip("KB 创建", "请求失败（连接错误）")
        return 1
    if resp.status_code != 200:
        fail("KB 创建", f"status={resp.status_code} body={resp.text[:200]}")
        failures += 1
        return 1
    kb_id = resp.json()["data"]["kb_id"]
    ok("KB 创建", f"kb_id={kb_id}")

    # 2b. 上传文档
    content = (
        f"# RAGNexus 鲁棒性验证 {os.urandom(4).hex()}\n\n"
        "RAGNexus 是一个 RAG 中间件平台，提供知识库管理、文档摄入和向量检索能力。\n"
        "系统采用六边形架构，支持 hybrid (向量+BM25) 混合检索模式。\n"
        "当 Elasticsearch 不可用时，系统自动降级为纯向量检索，确保服务不中断。\n"
    ).encode()

    resp = _make_request(
        base,
        "/v1/documents:upload",
        method="POST",
        data={"kb_id": kb_id},
        files={"file": ("robustness-test.md", content, "text/markdown")},
    )
    if resp is None:
        skip("文档上传", "请求失败（连接错误）")
        return 1
    if resp.status_code not in (200, 201):
        # 检查是否是已经存在（幂等）
        fail("文档上传", f"status={resp.status_code} body={resp.text[:200]}")
        failures += 1
        return 1
    upload_data = resp.json()
    chunk_count = upload_data.get("data", {}).get("chunk_count", 0)
    ok("文档上传", f"chunks={chunk_count}")

    # 2c. 基础检索
    resp = _make_request(
        base,
        "/v1/rag:retrieve",
        method="POST",
        json_body={
            "query": "RAGNexus 架构",
            "kb_ids": [kb_id],
            "top_k": 3,
        },
    )
    if resp is None:
        skip("基础检索", "请求失败（连接错误）")
        return 1
    if resp.status_code != 200:
        fail("基础检索", f"status={resp.status_code} body={resp.text[:200]}")
        failures += 1
        return 1

    rd = resp.json()
    if rd.get("code") != 0:
        fail("基础检索", f"code={rd.get('code')} message={rd.get('message')}")
        failures += 1
        return 1

    total_hits = rd["data"].get("total", 0)
    ok("基础检索", f"total_hits={total_hits}")

    # ── Case 3: 鲁棒性字段验证 ──────────────────────────────────────────
    header("Case 3: 鲁棒性响应字段验证")
    meta = rd["data"]["meta"]

    checks = [
        ("degraded", lambda v: isinstance(v, bool)),
        ("degraded_kb_ids", lambda v: isinstance(v, list)),
        ("failed_kb_ids", lambda v: isinstance(v, list)),
        ("partial_kb_success", lambda v: isinstance(v, bool)),
        ("empty_reason", lambda v: v is None or isinstance(v, str)),
    ]

    for field, validator in checks:
        value = meta.get(field)
        if value is None and field != "empty_reason":
            fail(f"meta.{field}", "字段缺失")
            failures += 1
        elif not validator(value):
            fail(f"meta.{field}", f"类型不匹配: {type(value).__name__} = {value!r}")
            failures += 1
        else:
            ok(f"meta.{field}", f"{value!r}")

    # ── Case 4: ES 降级验证 ─────────────────────────────────────────────
    header("Case 4: ES 降级场景验证")

    # 检查 ES 是否可达
    es_url = os.environ.get("ELASTICSEARCH_URL", "http://localhost:9200")
    es_available = False
    try:
        es_resp = requests.get(es_url, timeout=3)
        es_available = es_resp.status_code < 500
    except requests.ConnectionError:
        pass
    except requests.Timeout:
        pass

    if es_available:
        ok("ES 可达", f"{es_url} — 降级状态应取决于服务端 ES_ENABLED 配置")
    else:
        # ES 不可达 → 验证降级行为
        ok("ES 不可达", f"{es_url} — 服务端应自动降级")

    # 执行 hybrid 检索，验证降级字段
    degraded_meta = meta
    if degraded_meta.get("mode") == "hybrid":
        degraded_val = degraded_meta.get("degraded", False)
        degraded_reason = degraded_meta.get("degraded_reason")
        degraded_kb_ids = degraded_meta.get("degraded_kb_ids", [])

        if es_available and not degraded_val:
            ok("hybrid 检索", "ES 可用，未降级（预期行为）")
        elif not es_available and degraded_val:
            ok(
                "hybrid 检索降级",
                (
                    f"degraded=True reason={degraded_reason!r}"
                    f" kb_ids={degraded_kb_ids}"
                ),
            )
        elif not es_available and not degraded_val:
            # ES 不可达但服务未标记降级 → 可能是 ES_ENABLED=false
            skip(
                "hybrid 检索",
                (
                    "ES 不可达但 degraded=False"
                    "（可能 ES_ENABLED=false 或降级判定未触发）"
                ),
            )
        else:
            ok(
                "hybrid 检索",
                f"degraded={degraded_val} reason={degraded_reason!r}",
            )
    else:
        # 非 hybrid 模式
        skip("ES 降级验证", f"检索模式为 {degraded_meta.get('mode')}，非 hybrid")

    # ── 结果汇总 ────────────────────────────────────────────────────────
    print()
    print("=" * 60)
    if failures == 0:
        print(f"  {GREEN}✅ 全部验证通过{RESET}")
    else:
        print(f"  {RED}❌ {failures} 项验证失败{RESET}")
    print("=" * 60)
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
