"""PgKnowledgeBaseRepository — 知识库元数据 CRUD 适配器。

基于 asyncpg 实现 KnowledgeBasePort。
"""

import asyncpg
from nanoid import generate as nanoid_generate

from ragnexus.core.errors import AppError, ErrorCode
from ragnexus.domain.models import KnowledgeBase


class PgKnowledgeBaseRepository:
    """Postgres (asyncpg) 知识库元数据适配器。"""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def create(self, name: str, name_key: str) -> KnowledgeBase:
        """创建知识库。自动重试 nanoid 碰撞，只捕获 name_key 约束冲突。

        Raises:
            AppError(ErrorCode.RESOURCE_CONFLICT): name_key 重复时。
        """
        max_retries = 3
        for attempt in range(max_retries):
            kb_id = "kb_" + nanoid_generate(size=8)
            try:
                row = await self.pool.fetchrow(
                    "INSERT INTO knowledge_bases (id, name, name_key) VALUES ($1, $2, $3) "
                    "RETURNING id, name, created_at",
                    kb_id,
                    name,
                    name_key,
                )
                return KnowledgeBase(
                    id=row["id"], name=row["name"], created_at=row["created_at"]
                )
            except asyncpg.UniqueViolationError as e:
                # 检查冲突的约束名，区分 name_key 唯一冲突 vs kb_id 碰撞
                constraint: str = getattr(e, "constraint_name", "") or ""
                if "name_key" in constraint:
                    raise AppError(
                        ErrorCode.RESOURCE_CONFLICT,
                        "知识库名称已存在",
                        errors=[{"field": "name", "reason": f"{name!r} 已存在"}],
                    ) from e
                # pkey/id 约束 → kb_id 碰撞（nanoid 极小概率）→ 重试
                if "pkey" in constraint or "knowledge_bases_pkey" in constraint:
                    if attempt == max_retries - 1:
                        raise AppError(
                            ErrorCode.SERVER_ERROR, "知识库 ID 生成失败，请重试"
                        ) from e
                    continue
                # 无法识别约束名 → 保守当作 name_key 冲突
                raise AppError(
                    ErrorCode.RESOURCE_CONFLICT,
                    "知识库名称已存在",
                    errors=[{"field": "name", "reason": f"{name!r} 已存在"}],
                ) from e

    async def get(self, kb_id: str) -> KnowledgeBase | None:
        """按 ID 获取知识库，不存在返回 None。"""
        row = await self.pool.fetchrow(
            "SELECT id, name, created_at FROM knowledge_bases WHERE id=$1",
            kb_id,
        )
        return KnowledgeBase(**dict(row)) if row else None

    async def exists(self, kb_id: str) -> bool:
        """检查知识库是否按 ID 存在。"""
        return bool(
            await self.pool.fetchval(
                "SELECT 1 FROM knowledge_bases WHERE id=$1",
                kb_id,
            )
        )

    async def doc_exists(self, doc_id: str) -> bool:
        """检查文档是否按 doc_id 存在。"""
        return bool(
            await self.pool.fetchval(
                "SELECT 1 FROM documents WHERE doc_id=$1",
                doc_id,
            )
        )
