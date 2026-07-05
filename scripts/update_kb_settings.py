"""更新知识库 settings — 从 JSON 文件覆盖写入。

用法：
    uv run python scripts/update_kb_settings.py --kb-id kb_xxx --settings-file kb_settings.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import asyncpg

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ragnexus.adapters.knowledge_base.pg import PgKnowledgeBaseRepository  # noqa: E402
from ragnexus.config import get_settings  # noqa: E402
from ragnexus.core.errors import AppError  # noqa: E402


async def _update(kb_id: str, settings_file: str) -> None:
    """读取 JSON 文件并通过 PgKnowledgeBaseRepository 覆盖 KB settings。"""
    app_settings = get_settings()

    with open(settings_file, encoding="utf-8") as f:
        kb_settings = json.load(f)

    # 创建单连接池以复用 PgKnowledgeBaseRepository
    pool = await asyncpg.create_pool(app_settings.PG_DSN, min_size=1, max_size=1)
    try:
        repo = PgKnowledgeBaseRepository(pool)
        await repo.update_settings(kb_id, kb_settings)

        synonym_count = len(kb_settings.get("synonyms", []))
        print(f"Settings 已更新：kb_id={kb_id}, synonyms={synonym_count} 组")
    finally:
        await pool.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="覆盖知识库 settings（从 JSON 文件）")
    parser.add_argument("--kb-id", required=True, help="知识库 ID")
    parser.add_argument("--settings-file", required=True, help="settings JSON 文件路径")
    args = parser.parse_args()

    try:
        asyncio.run(_update(args.kb_id, args.settings_file))
    except AppError as e:
        print(f"错误 [{e.code}]: {e.message}", file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError:
        print(f"错误：文件不存在 — {args.settings_file}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"错误：JSON 解析失败 — {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
