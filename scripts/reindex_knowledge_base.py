#!/usr/bin/env python3
"""批量重建知识库索引。

对指定知识库下所有 status=SUCCESS 的文档执行 purge + 重新索引。
单篇失败不阻断其余文档，结束时打印统计。

用法:
    uv run python scripts/reindex_knowledge_base.py --kb-id kb_ecom
    uv run python scripts/reindex_knowledge_base.py --kb-id kb_ecom --document-id doc_aaa
"""

import argparse
import asyncio
import sys

import asyncpg

from ragnexus.config import get_settings
from ragnexus.domain.models import DocStatus
from ragnexus.tasks.indexing import index_document_task


async def main():
    parser = argparse.ArgumentParser(description="批量重建知识库索引")
    parser.add_argument("--kb-id", required=True, help="目标知识库 ID")
    parser.add_argument("--tenant-id", help="租户 ID（可选，不传时从 KB 记录反查）")
    parser.add_argument(
        "--document-id",
        action="append",
        default=[],
        help="指定文档 ID（可多次传入，不传则处理全部）",
    )
    args = parser.parse_args()

    settings = get_settings()
    pool = await asyncpg.create_pool(settings.PG_DSN, min_size=1, max_size=3)

    try:
        # 验证知识库存在
        kb = await pool.fetchrow(
            "SELECT id, name, tenant_id FROM knowledge_bases WHERE id = $1",
            args.kb_id,
        )
        if kb is None:
            print(f"错误: 知识库 {args.kb_id} 不存在")
            sys.exit(1)
        print(f"知识库: {kb['name']} (ID: {kb['id']})")

        # 查询待处理文档
        if args.document_id:
            docs = await pool.fetch(
                "SELECT doc_id, filename, status FROM documents "
                "WHERE kb_id = $1 AND doc_id = ANY($2) AND status = $3",
                args.kb_id,
                args.document_id,
                DocStatus.SUCCESS.value,
            )
        else:
            docs = await pool.fetch(
                "SELECT doc_id, filename, status FROM documents "
                "WHERE kb_id = $1 AND status = $2",
                args.kb_id,
                DocStatus.SUCCESS.value,
            )

        if not docs:
            print("没有需要 reindex 的文档")
            return

        print(f"共 {len(docs)} 篇文档待处理\n")

        success = 0
        failed = 0
        skipped = 0

        for doc in docs:
            doc_id = doc["doc_id"]
            filename = doc["filename"]

            # 二次确认状态（并发下可能变化）
            current = await pool.fetchrow(
                "SELECT status FROM documents WHERE doc_id = $1", doc_id
            )
            if current is None:
                print(f"  [SKIP] {filename}: 文档已不存在")
                skipped += 1
                continue
            if current["status"] != DocStatus.SUCCESS.value:
                print(
                    f"  [SKIP] {filename}: 状态不是 SUCCESS（当前: {current['status']}）"
                )
                skipped += 1
                continue

            try:
                # 清除旧 chunk: pgvector
                await pool.execute("DELETE FROM chunks WHERE doc_id = $1", doc_id)
                # 更新状态
                await pool.execute(
                    "UPDATE documents SET status = $1, error_message = NULL, "
                    "updated_at = NOW() WHERE doc_id = $2",
                    DocStatus.PROCESSING.value,
                    doc_id,
                )
                # 提交 Celery 任务
                index_document_task.apply_async(args=[doc_id], ignore_result=True)
                print(f"  [OK] {filename} → PROCESSING")
                success += 1
            except Exception as e:
                print(f"  [FAIL] {filename}: {e}")
                failed += 1

        print(f"\n--- 完成 ---")
        print(f"已处理: {success} 篇  失败: {failed} 篇  跳过: {skipped} 篇")

    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
