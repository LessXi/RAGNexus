#!/usr/bin/env python3
"""嵌入模型 & 大语言模型 连通性与延迟测试。

从 .env 读取配置，逐阶段测试：
  1. 嵌入模型 — TCP 连通 → API 调用延迟 → 维度校验
  2. 大语言模型 — TCP 连通 → 非流式延迟 → 流式 TTFT + 吞吐

用法:
  uv run python scripts/check_model_latency.py
  python scripts/check_model_latency.py        # 已激活 venv 时

依赖: httpx (已在 pyproject.toml dependencies 中)
"""

import asyncio
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

# 确保可从项目根运行 — 把 src/ 加入 sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

import httpx  # noqa: E402 (sys.path 必须先设置)

from ragnexus.config import get_settings  # noqa: E402

# ═════════════════════════════════════════════════════════════
#  ANSI 调色板
# ═════════════════════════════════════════════════════════════
C = {
    "R": "\033[0m",  # Reset
    "H": "\033[1;34m",  # Header — 阶段标题
    "G": "\033[1;32m",  # Green  — 成功
    "Y": "\033[1;33m",  # Yellow — 警告
    "E": "\033[1;31m",  # Red    — 错误
    "D": "\033[2;37m",  # Dim    — 次要信息
    "C": "\033[1;36m",  # Cyan   — 数值 / 关键数据
    "M": "\033[1;35m",  # Magenta — 指标名
}


# ═════════════════════════════════════════════════════════════
#  输出工具
# ═════════════════════════════════════════════════════════════


def log(emoji: str, msg: str, color: str = "") -> None:
    """带时间戳的单行日志，立即刷新。"""
    ts = time.strftime("%H:%M:%S")
    print(f"{C['D']}[{ts}]{C['R']} {emoji}  {color}{msg}{C['R']}", flush=True)


def stage(n: int, title: str) -> None:
    """阶段分隔标题。"""
    print()
    bar = "─" * 50
    print(f"{C['H']}{bar}{C['R']}")
    print(f"{C['H']}  阶段 {n}：{title}{C['R']}")
    print(f"{C['H']}{bar}{C['R']}", flush=True)


def ms(seconds: float) -> str:
    """秒 → 人类可读。"""
    if seconds < 1:
        return f"{C['C']}{seconds * 1000:.1f} ms{C['R']}"
    if seconds < 60:
        return f"{C['C']}{seconds:.2f} s{C['R']}"
    return f"{C['C']}{seconds / 60:.1f} min{C['R']}"


def dim(label: str, value: str) -> str:
    """次要信息行。"""
    return f"    {C['D']}{label}:{C['R']} {value}"


# ═════════════════════════════════════════════════════════════
#  底层网络探测
# ═════════════════════════════════════════════════════════════


async def _tcp_probe(host: str, port: int, timeout: float = 5.0) -> dict:
    """纯 TCP 三次握手延迟（不涉及 TLS）。"""
    t0 = time.perf_counter()
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=timeout,
        )
        elapsed = time.perf_counter() - t0
        writer.close()
        await writer.wait_closed()
        return {"ok": True, "elapsed": elapsed}
    except Exception as exc:
        return {"ok": False, "elapsed": time.perf_counter() - t0, "error": str(exc)}


async def _http_head_probe(url: str, timeout: float = 8.0) -> dict:
    """HTTP HEAD 请求 — 验证 TLS + HTTP 层可达。"""
    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.head(url, follow_redirects=True)
        elapsed = time.perf_counter() - t0
        return {"ok": True, "elapsed": elapsed, "status": resp.status_code}
    except httpx.ConnectError as exc:
        return {
            "ok": False,
            "elapsed": time.perf_counter() - t0,
            "error": f"连接失败: {exc}",
        }
    except httpx.TimeoutException:
        return {"ok": False, "elapsed": time.perf_counter() - t0, "error": "超时"}
    except Exception as exc:
        return {"ok": False, "elapsed": time.perf_counter() - t0, "error": str(exc)}


# ═════════════════════════════════════════════════════════════
#  嵌入模型测试
# ═════════════════════════════════════════════════════════════


async def test_embed_api(settings) -> dict:
    """向嵌入 API 发送单条文本，测量端到端延迟并校验维度。"""
    url = f"{settings.EMBED_BASE_URL}/embeddings"
    headers = {
        "Authorization": f"Bearer {settings.EMBED_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.EMBED_MODEL,
        "input": ["人工智能正在改变世界"],
    }

    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
    except (httpx.HTTPError, OSError) as exc:
        return {
            "ok": False,
            "elapsed": time.perf_counter() - t0,
            "status": 0,
            "body": str(exc),
        }
    elapsed = time.perf_counter() - t0

    if resp.status_code == 200:
        data = resp.json()
        vec = data["data"][0]["embedding"]
        usage = data.get("usage", {})
        return {
            "ok": True,
            "elapsed": elapsed,
            "http_elapsed": resp.elapsed.total_seconds(),
            "dim": len(vec),
            "tokens": usage.get("total_tokens", "N/A"),
            "model": data.get("model", "N/A"),
        }
    else:
        return {
            "ok": False,
            "elapsed": elapsed,
            "status": resp.status_code,
            "body": resp.text[:800],
        }


async def run_embed_stage(settings) -> None:
    """阶段 2：嵌入模型全链路。"""
    stage(2, "嵌入模型连通性 & 延迟")

    u = urlparse(settings.EMBED_BASE_URL)
    host = u.hostname or ""
    port = u.port or (443 if u.scheme == "https" else 80)

    # 2a — TCP
    log("🔌", f"TCP 连接 → {host}:{port} ...")
    tcp = await _tcp_probe(host, port)
    if tcp["ok"]:
        log("✅", "TCP 连通" + dim("延迟", ms(tcp["elapsed"])), C["G"])
    else:
        log("❌", f"TCP 不通 — {tcp['error']}", C["E"])
        return

    # 2b — HTTP HEAD
    log("🌐", f"HTTP HEAD → {settings.EMBED_BASE_URL} ...")
    head = await _http_head_probe(settings.EMBED_BASE_URL)
    if head["ok"]:
        log(
            "✅",
            f"HTTP 可达 (状态码 {head['status']})" + dim("延迟", ms(head["elapsed"])),
            C["G"],
        )
    else:
        log("⚠️", f"HTTP HEAD 异常 — {head.get('error', '')}（继续 API 测试）", C["Y"])

    # 2c — Embedding API
    log("📤", f"POST /embeddings  (model={settings.EMBED_MODEL}) ...")
    emb = await test_embed_api(settings)
    if emb["ok"]:
        log("✅", "Embedding API 调用成功", C["G"])
        print(dim("总延迟", ms(emb["elapsed"])))
        print(dim("HTTP 耗时", ms(emb["http_elapsed"])))
        print(dim("返回模型", str(emb["model"])))
        print(dim("向量维度", str(emb["dim"])))
        print(dim("消耗 Token", str(emb["tokens"])))
        if emb["dim"] != settings.EMBED_DIM:
            log("⚠️", f"维度不匹配！配置={settings.EMBED_DIM}  实际={emb['dim']}", C["Y"])
    else:
        log("❌", f"API 调用失败  HTTP {emb['status']}", C["E"])
        print(f"    {C['D']}{emb['body'][:500]}{C['R']}")


# ═════════════════════════════════════════════════════════════
#  LLM 测试
# ═════════════════════════════════════════════════════════════


async def test_llm_non_stream(settings) -> dict:
    """非流式 Chat Completion — 测总延迟。"""
    url = f"{settings.LLM_BASE_URL}/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.LLM_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.LLM_MODEL,
        "messages": [{"role": "user", "content": "请用一句话介绍你自己"}],
        "max_tokens": 64,
        "stream": False,
    }

    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
    except (httpx.HTTPError, OSError) as exc:
        return {
            "ok": False,
            "elapsed": time.perf_counter() - t0,
            "status": 0,
            "body": str(exc),
        }
    elapsed = time.perf_counter() - t0

    if resp.status_code == 200:
        data = resp.json()
        choice = data["choices"][0]
        usage = data.get("usage", {})
        return {
            "ok": True,
            "elapsed": elapsed,
            "http_elapsed": resp.elapsed.total_seconds(),
            "content": choice["message"]["content"].strip(),
            "finish_reason": choice.get("finish_reason", "N/A"),
            "prompt_tokens": usage.get("prompt_tokens", "N/A"),
            "completion_tokens": usage.get("completion_tokens", "N/A"),
        }
    else:
        return {
            "ok": False,
            "elapsed": elapsed,
            "status": resp.status_code,
            "body": resp.text[:800],
        }


async def test_llm_stream(settings) -> dict:
    """流式 Chat Completion — 测 TTFT 和生成吞吐。"""
    url = f"{settings.LLM_BASE_URL}/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.LLM_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.LLM_MODEL,
        "messages": [{"role": "user", "content": "请用50字左右介绍深度学习"}],
        "max_tokens": 128,
        "stream": True,
    }

    t_start = time.perf_counter()
    ttft: float | None = None
    chunk_count = 0
    total_chars = 0
    finish_reason = "N/A"

    try:
        async with httpx.AsyncClient(  # noqa: SIM117 (stream 需存活)
            timeout=60.0
        ) as client:
            async with client.stream("POST", url, json=payload, headers=headers) as resp:
                if resp.status_code != 200:
                    body = await resp.aread()
                    return {
                        "ok": False,
                        "elapsed": time.perf_counter() - t_start,
                        "status": resp.status_code,
                        "body": body.decode(errors="replace")[:800],
                    }

                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    if data_str.strip() == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue
                    choices = chunk.get("choices")
                    if not choices:
                        continue
                    choice = choices[0]
                    delta = choice.get("delta") or {}
                    # DeepSeek V4 等模型流式输出时文本可能在 reasoning_content 中
                    content = delta.get("content") or delta.get("reasoning_content") or ""
                    if content:
                        if ttft is None:
                            ttft = time.perf_counter() - t_start
                        chunk_count += 1
                        total_chars += len(content)
                    if choice.get("finish_reason"):
                        finish_reason = choice["finish_reason"]
    except (httpx.HTTPError, OSError) as exc:
        return {
            "ok": False,
            "elapsed": time.perf_counter() - t_start,
            "status": 0,
            "body": str(exc),
        }

    t_total = time.perf_counter() - t_start

    if ttft is None:
        return {
            "ok": False,
            "elapsed": t_total,
            "error": "未收到任何 token（可能是空响应）",
        }

    gen_time = t_total - ttft
    return {
        "ok": True,
        "elapsed": t_total,
        "ttft": ttft,
        "gen_time": gen_time,
        "chunk_count": chunk_count,
        "total_chars": total_chars,
        "chars_per_sec": total_chars / gen_time if gen_time > 0 else 0,
        "finish_reason": finish_reason,
    }


async def run_llm_stage(settings) -> None:
    """阶段 3：LLM 全链路。"""
    stage(3, "LLM 连通性 & 延迟")

    u = urlparse(settings.LLM_BASE_URL)
    host = u.hostname or ""
    port = u.port or (443 if u.scheme == "https" else 80)

    # 3a — TCP
    log("🔌", f"TCP 连接 → {host}:{port} ...")
    tcp = await _tcp_probe(host, port)
    if tcp["ok"]:
        log("✅", "TCP 连通" + dim("延迟", ms(tcp["elapsed"])), C["G"])
    else:
        log("❌", f"TCP 不通 — {tcp['error']}", C["E"])
        return

    # 3b — HTTP HEAD
    log("🌐", f"HTTP HEAD → {settings.LLM_BASE_URL} ...")
    head = await _http_head_probe(settings.LLM_BASE_URL)
    if head["ok"]:
        log(
            "✅",
            f"HTTP 可达 (状态码 {head['status']})" + dim("延迟", ms(head["elapsed"])),
            C["G"],
        )
    else:
        log("⚠️", f"HTTP HEAD 异常 — {head.get('error', '')}（继续 API 测试）", C["Y"])

    # 3c — 非流式
    log("📤", f"非流式 Chat  (model={settings.LLM_MODEL}) ...")
    ns = await test_llm_non_stream(settings)
    if ns["ok"]:
        log("✅", "非流式调用成功", C["G"])
        print(dim("总延迟", ms(ns["elapsed"])))
        print(dim("HTTP 耗时", ms(ns["http_elapsed"])))
        print(dim("回复内容", f"{C['C']}{ns['content']}{C['R']}"))
        print(dim("Prompt Token", str(ns["prompt_tokens"])))
        print(dim("Completion Token", str(ns["completion_tokens"])))
        print(dim("结束原因", str(ns["finish_reason"])))
    else:
        log("❌", f"非流式调用失败  HTTP {ns['status']}", C["E"])
        print(f"    {C['D']}{ns['body'][:500]}{C['R']}")

    # 3d — 流式
    log("📤", "流式 Chat  (测 TTFT + 吞吐) ...")
    ss = await test_llm_stream(settings)
    if ss["ok"]:
        log("✅", "流式调用成功", C["G"])
        print(dim("总延迟", ms(ss["elapsed"])))
        print(dim("TTFT（首 Token）", ms(ss["ttft"])))
        print(dim("生成耗时", ms(ss["gen_time"])))
        print(dim("Chunk 数", str(ss["chunk_count"])))
        print(dim("输出字符数", str(ss["total_chars"])))
        tps = ss["chars_per_sec"]
        print(dim("生成速度", f"{C['C']}{tps:.1f} 字符/秒{C['R']}"))
        print(dim("结束原因", str(ss["finish_reason"])))
    else:
        log("❌", f"流式调用失败  HTTP {ss.get('status', '?')}", C["E"])
        print(f"    {C['D']}{ss.get('body', ss.get('error', ''))[:500]}{C['R']}")


# ═════════════════════════════════════════════════════════════
#  主入口
# ═════════════════════════════════════════════════════════════


async def main() -> None:
    print(f"{C['H']}╔══════════════════════════════════════════════════════╗{C['R']}")
    print(f"{C['H']}║     RAGNexus  模型连通性 & 延迟测试                ║{C['R']}")
    print(f"{C['H']}╚══════════════════════════════════════════════════════╝{C['R']}")

    # ── 阶段 1：加载配置 ──
    stage(1, "加载 .env 配置")
    try:
        cfg = get_settings()
    except Exception as exc:
        log("❌", f"无法加载配置: {exc}", C["E"])
        sys.exit(1)

    print(
        dim(
            "嵌入",
            f"{C['C']}{cfg.EMBED_MODEL}{C['R']}  {C['D']}→{C['R']} {cfg.EMBED_BASE_URL}",
        )
    )
    print(
        dim(
            "LLM ",
            f"{C['C']}{cfg.LLM_MODEL}{C['R']}  {C['D']}→{C['R']} {cfg.LLM_BASE_URL}",
        )
    )

    missing: list[str] = []
    if not cfg.EMBED_API_KEY:
        missing.append("EMBED_API_KEY")
    if not cfg.LLM_API_KEY:
        missing.append("LLM_API_KEY")
    if missing:
        log("⚠️", f"以下 API Key 为空，将跳过对应测试: {', '.join(missing)}", C["Y"])

    # ── 阶段 2 ──
    if cfg.EMBED_API_KEY:
        await run_embed_stage(cfg)
    else:
        log("⏭️", "跳过嵌入模型测试（无 API Key）", C["Y"])

    # ── 阶段 3 ──
    if cfg.LLM_API_KEY:
        await run_llm_stage(cfg)
    else:
        log("⏭️", "跳过 LLM 测试（无 API Key）", C["Y"])

    # ── 汇总 ──
    stage(4, "测试完毕")
    print(f"\n    {C['G']}所有可达模型已完成连通性与延迟检测。{C['R']}\n")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(f"\n{C['Y']}⏹️  用户中断{C['R']}")
        sys.exit(130)
