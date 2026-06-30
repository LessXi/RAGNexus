"""RAGNexus 检索管线 A/B 测试脚本
用法: uv run python scripts/retrieve_ab_test.py [baseline|full]
"""

import asyncio
import json
import sys
import time

import httpx

BASE = "http://localhost:8000"
KB_ID = "kb_3FtAzN4Z"

QUERIES = [
    ("口语-智能助手", "怎么做智能助手"),
    ("口语-检索效果", "怎么提升检索效果"),
    ("专业-RAG流程", "RAG检索增强生成流程"),
    ("专业-RLHF", "RLHF对齐训练方法"),
    ("短-Agent", "Agent"),
]

WARMUP_QUERIES = ["warmup-1", "warmup-2", "warmup-3"]


async def retrieve(client: httpx.AsyncClient, query: str, label: str, req_id: str) -> dict:
    t0 = time.perf_counter()
    try:
        resp = await client.post(
            f"{BASE}/v1/rag:retrieve",
            json={"query": query, "kb_ids": [KB_ID], "top_k": 5},
            headers={"X-Request-ID": req_id},
            timeout=90,
        )
        elapsed = time.perf_counter() - t0
        data = resp.json()
        payload = data.get("data", {})
        hits = payload.get("hits", [])
        scores = [h["score"] for h in hits[:5]]
        mono = (
            all(scores[i] >= scores[i + 1] for i in range(len(scores) - 1))
            if len(scores) >= 2
            else True
        )
        return {
            "label": label,
            "query": query,
            "elapsed_s": round(elapsed, 4),
            "status": resp.status_code,
            "total": len(hits),
            "hit_ids": [h["chunk_id"] for h in hits[:5]],
            "hit_scores": scores,
            "monotonic": mono,
            "query_rewritten": payload.get("query_rewritten"),
        }
    except Exception as e:
        elapsed = time.perf_counter() - t0
        return {
            "label": label,
            "query": query,
            "elapsed_s": round(elapsed, 4),
            "error": str(e),
        }


async def warmup(client: httpx.AsyncClient):
    print("=== 预热 (3 queries) ===")
    for i, q in enumerate(WARMUP_QUERIES):
        r = await retrieve(client, q, f"warmup-{i}", f"warmup-{i}")
        print(f"  预热{i + 1}: {r.get('elapsed_s', 0) * 1000:.0f}ms")
        await asyncio.sleep(1)
    print("预热完成\n")


async def run_rounds(client: httpx.AsyncClient, mode: str, rounds: int = 3) -> list[dict]:
    results = []
    for q_idx, (label, query) in enumerate(QUERIES, 1):
        query_results = []
        for rnd in range(rounds):
            uniq = f"{mode}-Q{q_idx}-R{rnd + 1}"
            r = await retrieve(client, query, label, uniq)
            query_results.append(r)
            await asyncio.sleep(0.8)
        lats = [r.get("elapsed_s", 0) for r in query_results]
        lat_str = " → ".join(f"{lat * 1000:.0f}ms" for lat in lats)
        cold = "⚠冷启动" if len(lats) >= 2 and lats[0] > lats[-1] * 1.5 else ""
        mono_ok = all(r.get("monotonic", True) for r in query_results)
        mono_str = "✅单调" if mono_ok else "🔀重排"
        print(f"  {label:20s} | {lat_str:30s} | {cold:10s} | {mono_str}")
        results.append({"query_label": label, "query_text": query, "runs": query_results})
    return results


async def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "baseline"
    outfile = f"F:/learnAgent/MyProjects/RAGNexus/admin/test_{mode}.json"

    async with httpx.AsyncClient() as client:
        await warmup(client)
        print(f"=== {mode.upper()} 模式 (3 rounds each) ===")
        results = await run_rounds(client, mode, rounds=3)

    summary = {
        "mode": mode,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "kb_id": KB_ID,
        "results": results,
    }
    with open(outfile, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    all_lats = [
        r["elapsed_s"]
        for qr in results
        for r in qr["runs"]
        if "elapsed_s" in r and "error" not in r
    ]
    if all_lats:
        avg = sum(all_lats) / len(all_lats)
        print(
            f"\n平均: {avg * 1000:.0f}ms | min: {min(all_lats) * 1000:.0f}ms | max: {max(all_lats) * 1000:.0f}ms | 总计: {len(all_lats)} 请求"
        )
    print(f"结果已保存: {outfile}")


asyncio.run(main())
