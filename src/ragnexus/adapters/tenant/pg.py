"""PgTenantRepository / PgApiKeyRepository — 租户与 API 密钥 CRUD 适配器。

基于 asyncpg 实现多租户持久化层。
"""

from datetime import datetime

import asyncpg

from ragnexus.core.errors import AppError, ErrorCode
from ragnexus.domain.models import ApiKey, Tenant


class PgTenantRepository:
    """租户持久化仓库（PostgreSQL）。"""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self.pool = pool

    async def create(self, id: str, name: str) -> Tenant:
        """创建租户，重复 ID 抛出 ConflictError。

        Raises:
            AppError(ErrorCode.RESOURCE_CONFLICT): 租户 ID 已存在时。
        """
        try:
            row = await self.pool.fetchrow(
                "INSERT INTO tenants (id, name) VALUES ($1, $2) "
                "RETURNING id, name, status, created_at",
                id,
                name,
            )
        except asyncpg.UniqueViolationError as e:
            raise AppError(
                ErrorCode.RESOURCE_CONFLICT,
                "租户 ID 已存在",
                errors=[{"field": "id", "reason": f"租户 {id!r} 已存在"}],
            ) from e
        return Tenant(
            id=row["id"],
            name=row["name"],
            status=row["status"],
            created_at=row["created_at"],
        )

    async def get(self, id: str) -> Tenant | None:
        """按 ID 查询租户，不存在返回 None。"""
        row = await self.pool.fetchrow(
            "SELECT id, name, status, plan, created_at FROM tenants WHERE id = $1", id
        )
        if row is None:
            return None
        return Tenant(
            id=row["id"],
            name=row["name"],
            status=row["status"],
            plan=row.get("plan", "free"),
            created_at=row["created_at"],
        )

    async def list(self) -> list[Tenant]:
        """列出全部租户，按创建时间升序排列。"""
        rows = await self.pool.fetch(
            "SELECT id, name, status, created_at FROM tenants ORDER BY created_at"
        )
        return [
            Tenant(
                id=r["id"],
                name=r["name"],
                status=r["status"],
                created_at=r["created_at"],
            )
            for r in rows
        ]


class PgApiKeyRepository:
    """API 密钥持久化仓库（PostgreSQL）。密钥原文不存储，只存 SHA-256 哈希。"""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self.pool = pool

    async def create(
        self,
        tenant_id: str,
        key_hash: str,
        key_prefix: str,
        name: str,
        expires_at: datetime | None = None,
    ) -> ApiKey:
        """创建 API Key，key_hash 重复抛出 ConflictError。

        Raises:
            AppError(ErrorCode.RESOURCE_CONFLICT): key_hash 已存在时。
        """
        try:
            row = await self.pool.fetchrow(
                """
                INSERT INTO api_keys (tenant_id, key_hash, key_prefix, name, expires_at)
                VALUES ($1, $2, $3, $4, $5)
                RETURNING id::text, tenant_id, key_hash, key_prefix, name,
                          status, expires_at, created_at
                """,
                tenant_id,
                key_hash,
                key_prefix,
                name,
                expires_at,
            )
        except asyncpg.UniqueViolationError as e:
            raise AppError(
                ErrorCode.RESOURCE_CONFLICT,
                "密钥哈希已存在",
                errors=[{"field": "key_hash", "reason": "key_hash 重复"}],
            ) from e
        return ApiKey(
            id=row["id"],
            tenant_id=row["tenant_id"],
            key_hash=row["key_hash"],
            key_prefix=row["key_prefix"],
            name=row["name"],
            status=row["status"],
            expires_at=row["expires_at"],
            created_at=row["created_at"],
        )

    async def get_by_hash(self, key_hash: str) -> dict | None:
        """按 key_hash 查询，JOIN tenants 返回完整记录（含租户信息）。

        返回 None 表示 Key 不存在。
        """
        row = await self.pool.fetchrow(
            """
            SELECT ak.id::text AS key_id, ak.tenant_id, ak.key_hash, ak.key_prefix,
                   ak.name AS key_name, ak.status AS key_status,
                   ak.expires_at, ak.created_at,
                   t.name AS tenant_name, t.status AS tenant_status,
                   t.plan AS tenant_plan
            FROM api_keys ak
            JOIN tenants t ON t.id = ak.tenant_id
            WHERE ak.key_hash = $1
            """,
            key_hash,
        )
        if row is None:
            return None
        return dict(row)
