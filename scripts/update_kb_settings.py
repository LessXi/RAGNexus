"""更新知识库 settings。

用法：
    # 覆盖写入
    uv run python scripts/update_kb_settings.py --kb-id kb_xxx --settings-file kb_settings.json
    # 合并（增量添加词表，按 terms 去重）
    uv run python scripts/update_kb_settings.py --kb-id kb_xxx --merge --settings-file new_synonyms.json
    # 删除指定词组
    uv run python scripts/update_kb_settings.py --kb-id kb_xxx --remove-terms 背调 薪酬
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
    """读取 JSON 文件并覆盖 KB settings。"""
    app_settings = get_settings()

    with open(settings_file, encoding="utf-8") as f:
        kb_settings = json.load(f)

    pool = await asyncpg.create_pool(app_settings.PG_DSN, min_size=1, max_size=1)
    try:
        repo = PgKnowledgeBaseRepository(pool)
        await repo.update_settings(kb_id, kb_settings)
        synonym_count = len(kb_settings.get("synonyms", []))
        print(f"Settings 已更新：kb_id={kb_id}, synonyms={synonym_count} 组")
    finally:
        await pool.close()


async def _merge(kb_id: str, settings_file: str) -> None:
    """合并模式：读取现有 settings，与文件中新词表去重合并后写回。"""
    app_settings = get_settings()

    with open(settings_file, encoding="utf-8") as f:
        new_settings = json.load(f)

    new_synonyms = new_settings.get("synonyms", [])
    if not new_synonyms:
        print("文件中无 synonyms 字段，跳过合并")
        return

    pool = await asyncpg.create_pool(app_settings.PG_DSN, min_size=1, max_size=1)
    try:
        repo = PgKnowledgeBaseRepository(pool)
        existing_raw = await repo.get_settings(kb_id)
        existing = (
            json.loads(existing_raw)
            if isinstance(existing_raw, str)
            else (existing_raw or {})
        )
        existing_synonyms = (
            existing.get("synonyms", []) if isinstance(existing, dict) else []
        )

        # 按 terms 去重合并
        existing_term_sets = {
            frozenset(g.get("terms", []))
            for g in existing_synonyms
            if isinstance(g, dict)
        }

        added = 0
        for group in new_synonyms:
            if not isinstance(group, dict):
                continue
            term_set = frozenset(group.get("terms", []))
            if term_set and term_set not in existing_term_sets:
                existing_synonyms.append(group)
                existing_term_sets.add(term_set)
                added += 1

        merged = dict(existing)
        merged["synonyms"] = existing_synonyms
        if "rewrite_hint" in new_settings:
            merged["rewrite_hint"] = new_settings["rewrite_hint"]

        await repo.update_settings(kb_id, merged)
        print(
            f"合并完成：kb_id={kb_id}, 新增 {added} 组, 总计 {len(existing_synonyms)} 组"
        )
    finally:
        await pool.close()


async def _remove_terms(kb_id: str, terms: list[str]) -> None:
    """删除模式：移除包含指定 term 的 synonym 组。"""
    app_settings = get_settings()
    term_set = set(terms)

    pool = await asyncpg.create_pool(app_settings.PG_DSN, min_size=1, max_size=1)
    try:
        repo = PgKnowledgeBaseRepository(pool)
        existing_raw = await repo.get_settings(kb_id)
        existing = (
            json.loads(existing_raw)
            if isinstance(existing_raw, str)
            else (existing_raw or {})
        )
        existing_synonyms = (
            existing.get("synonyms", []) if isinstance(existing, dict) else []
        )

        removed = 0
        kept = []
        for group in existing_synonyms:
            if not isinstance(group, dict):
                kept.append(group)
                continue
            group_terms = set(group.get("terms", []))
            if group_terms & term_set:
                removed += 1
            else:
                kept.append(group)

        merged = dict(existing)
        merged["synonyms"] = kept
        await repo.update_settings(kb_id, merged)
        print(f"删除完成：kb_id={kb_id}, 移除 {removed} 组, 剩余 {len(kept)} 组")
    finally:
        await pool.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="管理知识库 settings")
    parser.add_argument("--kb-id", required=True, help="知识库 ID")
    parser.add_argument(
        "--settings-file", help="settings JSON 文件路径（覆盖/合并时使用）"
    )
    parser.add_argument(
        "--merge", action="store_true", help="合并模式：与现有词表去重合并"
    )
    parser.add_argument(
        "--remove-terms",
        nargs="+",
        metavar="TERM",
        help="删除包含指定 term 的 synonym 组",
    )
    args = parser.parse_args()

    if args.remove_terms:
        try:
            asyncio.run(_remove_terms(args.kb_id, args.remove_terms))
        except AppError as e:
            print(f"错误 [{e.code}]: {e.message}", file=sys.stderr)
            sys.exit(1)
    elif args.merge and args.settings_file:
        try:
            asyncio.run(_merge(args.kb_id, args.settings_file))
        except (AppError, FileNotFoundError, json.JSONDecodeError) as e:
            print(f"错误: {e}", file=sys.stderr)
            sys.exit(1)
    elif args.settings_file:
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
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
