"""从知识库文档中提取专业术语并生成同义词草稿。

遍历 KB 所有 chunk，采样后调用 LLM 提取领域术语，输出 kb_settings.json 草稿。

用法：
    uv run python scripts/generate_synonyms.py --kb-id kb_xxx > kb_settings.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import asyncpg
import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ragnexus.config import get_settings  # noqa: E402

# 采样上限：避免 token 超限
_MAX_CHUNKS = 40
_MAX_CHARS_PER_CHUNK = 600

# LLM 提取术语的 system prompt
_TERM_EXTRACTION_PROMPT = (
    "你是知识库术语提取助手。分析以下知识库文档片段，提取其中的专业术语、缩写、行业黑话，"
    "并建议同义词和扩展词。\n\n"
    "要求：\n"
    "1. 识别领域专业术语（包括缩写、简称、行业黑话）\n"
    "2. 将同义术语归为一组，terms 字段列出同义/近义术语，expand 列出可扩展的相关术语\n"
    "3. terms 和 expand 中至少各有一项\n"
    "4. rewrite_hint 简要描述知识库所属领域和常见缩写规则\n"
    "5. 只输出 JSON，不要 markdown 代码块，不要解释性文字\n\n"
    "输出格式：\n"
    "{\n"
    '  "synonyms": [\n'
    '    {"terms": ["术语", "缩写"], "expand": ["扩展词", "相关词"]},\n'
    "    ...\n"
    "  ],\n"
    '  "rewrite_hint": "本知识库包含XXX领域文档，常见缩写：...=..."\n'
    "}"
)


async def _fetch_chunks(kb_id: str, dsn: str) -> list[str]:
    """从数据库获取指定 KB 的 chunk 文本列表（采样截断）。"""
    conn = await asyncpg.connect(dsn)
    try:
        rows = await conn.fetch(
            "SELECT text FROM chunks WHERE kb_id = $1 LIMIT $2",
            kb_id,
            _MAX_CHUNKS,
        )
        if not rows:
            print(
                f"警告：知识库 {kb_id} 没有 chunk 数据，无法生成同义词建议",
                file=sys.stderr,
            )
            return []
        return [row["text"][:_MAX_CHARS_PER_CHUNK] for row in rows]
    finally:
        await conn.close()


async def _call_llm(
    context: str,
    base_url: str,
    api_key: str,
    model: str,
    timeout: float,
) -> dict:
    """调用 LLM 提取术语，返回解析后的 JSON 响应。"""
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": _TERM_EXTRACTION_PROMPT},
                    {"role": "user", "content": context},
                ],
                "temperature": 0.0,
            },
        )
        response.raise_for_status()
    data = response.json()

    content = data["choices"][0]["message"]["content"]
    # 防御：去除可能的 markdown 代码块包裹
    content = content.strip()
    if content.startswith("```"):
        # 去掉 ```json 和结尾 ```
        lines = content.split("\n")
        content = "\n".join(lines[1:-1] if len(lines) > 2 else lines[1:])
        content = content.strip()

    return json.loads(content)


async def _generate(kb_id: str) -> dict | None:
    """主逻辑：采样 chunk → LLM 提取 → 返回 draft settings dict。"""
    app_settings = get_settings()

    texts = await _fetch_chunks(kb_id, app_settings.PG_DSN)
    if not texts:
        return None

    context = "\n\n---\n\n".join(texts)

    print("正在调用 LLM 提取术语...", file=sys.stderr)
    try:
        result = await _call_llm(
            context=context,
            base_url=app_settings.LLM_BASE_URL,
            api_key=app_settings.LLM_API_KEY,
            model=app_settings.LLM_MODEL,
            timeout=app_settings.LLM_REQUEST_TIMEOUT,
        )
    except httpx.HTTPError as e:
        print(f"错误：LLM 调用失败 — {e}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"错误：LLM 响应 JSON 解析失败 — {e}", file=sys.stderr)
        sys.exit(1)

    # 确保必含字段
    result.setdefault("synonyms", [])
    result.setdefault("rewrite_hint", "")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="从知识库文档中提取专业术语并生成同义词草稿"
    )
    parser.add_argument("--kb-id", required=True, help="知识库 ID")
    args = parser.parse_args()

    draft = asyncio.run(_generate(args.kb_id))
    if draft is None:
        sys.exit(1)

    print("// 请人工审核后使用", file=sys.stderr)
    print(json.dumps(draft, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
