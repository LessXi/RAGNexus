"""Integration tests for PgTenantRepository and PgApiKeyRepository
with real PostgreSQL (test-db at localhost:15433).
"""

import uuid
from datetime import UTC, datetime

import pytest

from ragnexus.adapters.tenant.pg import PgApiKeyRepository, PgTenantRepository
from ragnexus.core.errors import AppError, ErrorCode
from ragnexus.domain.models import ApiKey, Tenant

pytestmark = [pytest.mark.integration]


def _unique_id() -> str:
    """生成唯一的测试用租户 ID（含时间戳和随机后缀，避免跨运行碰撞）。"""
    return f"t-int-{uuid.uuid4().hex[:8]}"


# ============================================================================
# PgTenantRepository
# ============================================================================


class TestPgTenantRepo:
    """PgTenantRepository 集成测试。"""

    async def test_create_and_get(self, pg_pool):
        """create 后 get 应返回同一租户。"""
        repo = PgTenantRepository(pg_pool)
        tid = _unique_id()

        tenant = await repo.create(id=tid, name="集成测试租户")

        assert isinstance(tenant, Tenant)
        assert tenant.id == tid
        assert tenant.name == "集成测试租户"
        assert tenant.status == "active"
        assert tenant.created_at is not None

        fetched = await repo.get(tid)
        assert fetched is not None
        assert fetched.id == tid
        assert fetched.name == "集成测试租户"

    async def test_get_not_found(self, pg_pool):
        """查询不存在租户应返回 None。"""
        repo = PgTenantRepository(pg_pool)
        result = await repo.get("nonexistent_tenant_99999")
        assert result is None

    async def test_duplicate_id_raises_conflict(self, pg_pool):
        """重复 ID 应抛出 ConflictError。"""
        repo = PgTenantRepository(pg_pool)
        tid = _unique_id()
        await repo.create(id=tid, name="first")

        with pytest.raises(AppError) as exc_info:
            await repo.create(id=tid, name="second")

        assert exc_info.value.code == ErrorCode.RESOURCE_CONFLICT.code
        assert exc_info.value.http_status == 409
        assert "已存在" in exc_info.value.message

    async def test_list_returns_all(self, pg_pool):
        """list 应返回所有租户。"""
        repo = PgTenantRepository(pg_pool)
        tid1 = _unique_id()
        tid2 = _unique_id()
        await repo.create(id=tid1, name="A")
        await repo.create(id=tid2, name="B")

        result = await repo.list()

        # 至少包含我们创建的（加上 default 租户）
        ids = [t.id for t in result]
        assert tid1 in ids
        assert tid2 in ids

    async def test_list_includes_default(self, pg_pool):
        """list 应包含迁移创建的 default 租户。"""
        repo = PgTenantRepository(pg_pool)
        result = await repo.list()
        ids = [t.id for t in result]
        assert "default" in ids


# ============================================================================
# PgApiKeyRepository
# ============================================================================


class TestPgApiKeyRepo:
    """PgApiKeyRepository 集成测试。"""

    async def test_create_and_get_by_hash(self, pg_pool):
        """create 后 get_by_hash 应返回完整记录（含租户信息）。"""
        tenant_repo = PgTenantRepository(pg_pool)
        apikey_repo = PgApiKeyRepository(pg_pool)

        tid = _unique_id()
        await tenant_repo.create(id=tid, name="密钥测试租户")

        key_hash = f"sha256:test_{uuid.uuid4().hex[:12]}"
        api_key = await apikey_repo.create(
            tenant_id=tid,
            key_hash=key_hash,
            key_prefix="rk_test",
            name="测试密钥",
        )

        assert isinstance(api_key, ApiKey)
        assert api_key.tenant_id == tid
        assert api_key.key_hash == key_hash
        assert api_key.key_prefix == "rk_test"
        assert api_key.status == "active"
        assert api_key.created_at is not None

        result = await apikey_repo.get_by_hash(key_hash)
        assert result is not None
        assert result["key_id"] == api_key.id
        assert result["tenant_name"] == "密钥测试租户"
        assert result["tenant_status"] == "active"
        assert result["key_status"] == "active"

    async def test_get_by_hash_not_found(self, pg_pool):
        """不存在的 key_hash 应返回 None。"""
        repo = PgApiKeyRepository(pg_pool)
        result = await repo.get_by_hash("nonexistent_hash_99999")
        assert result is None

    async def test_create_with_expires_at(self, pg_pool):
        """应支持设置过期时间。"""
        tenant_repo = PgTenantRepository(pg_pool)
        apikey_repo = PgApiKeyRepository(pg_pool)

        tid = _unique_id()
        await tenant_repo.create(id=tid, name="过期测试")

        expires = datetime(2027, 7, 4, 12, 0, 0, tzinfo=UTC)
        key_hash = f"sha256:exp_{uuid.uuid4().hex[:12]}"
        api_key = await apikey_repo.create(
            tenant_id=tid,
            key_hash=key_hash,
            key_prefix="rk_exp",
            name="过期密钥",
            expires_at=expires,
        )

        assert api_key.expires_at is not None

        result = await apikey_repo.get_by_hash(key_hash)
        assert result is not None
        assert result["expires_at"] is not None

    async def test_duplicate_hash_raises_conflict(self, pg_pool):
        """重复 key_hash 应抛出 ConflictError。"""
        tenant_repo = PgTenantRepository(pg_pool)
        apikey_repo = PgApiKeyRepository(pg_pool)

        tid = _unique_id()
        await tenant_repo.create(id=tid, name="冲突测试")

        key_hash = f"sha256:dup_{uuid.uuid4().hex[:12]}"
        await apikey_repo.create(
            tenant_id=tid,
            key_hash=key_hash,
            key_prefix="rk_dup",
            name="first",
        )

        with pytest.raises(AppError) as exc_info:
            await apikey_repo.create(
                tenant_id=tid,
                key_hash=key_hash,
                key_prefix="rk_dup",
                name="second",
            )

        assert exc_info.value.code == ErrorCode.RESOURCE_CONFLICT.code
        assert exc_info.value.http_status == 409
        assert "已存在" in exc_info.value.message
