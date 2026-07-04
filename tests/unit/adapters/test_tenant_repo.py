"""Tests for PgTenantRepository and PgApiKeyRepository — TDD RED phase."""

from datetime import datetime
from unittest.mock import AsyncMock

import asyncpg
import pytest

from ragnexus.adapters.tenant.pg import PgApiKeyRepository, PgTenantRepository
from ragnexus.core.errors import AppError
from ragnexus.domain.models import ApiKey, Tenant


@pytest.fixture
def mock_pool():
    """返回 asyncpg.Pool 的 AsyncMock。"""
    return AsyncMock()


@pytest.fixture
def tenant_repo(mock_pool):
    """返回使用 mock pool 的 PgTenantRepository。"""
    return PgTenantRepository(pool=mock_pool)


@pytest.fixture
def apikey_repo(mock_pool):
    """返回使用 mock pool 的 PgApiKeyRepository。"""
    return PgApiKeyRepository(pool=mock_pool)


# ============================================================================
# PgTenantRepository
# ============================================================================


class TestTenantCreate:
    """PgTenantRepository.create() 测试。"""

    @pytest.mark.asyncio
    async def test_create_success(self, tenant_repo, mock_pool):
        """create() 应 INSERT tenants 并返回 Tenant 领域模型。"""
        now = datetime(2026, 7, 4, 12, 0, 0)
        mock_pool.fetchrow.return_value = {
            "id": "t-org1",
            "name": "组织一",
            "status": "active",
            "created_at": now,
        }

        result = await tenant_repo.create(id="t-org1", name="组织一")

        assert isinstance(result, Tenant)
        assert result.id == "t-org1"
        assert result.name == "组织一"
        assert result.status == "active"
        assert result.created_at == now
        mock_pool.fetchrow.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_create_duplicate_id_raises_conflict(self, tenant_repo, mock_pool):
        """create() 应在重复 ID 时抛出 ConflictError。"""
        mock_pool.fetchrow.side_effect = asyncpg.UniqueViolationError(
            "duplicate key value violates unique constraint"
        )

        with pytest.raises(AppError) as exc_info:
            await tenant_repo.create(id="t-org1", name="组织一")

        assert exc_info.value.message == "租户 ID 已存在"


class TestTenantGet:
    """PgTenantRepository.get() 测试。"""

    @pytest.mark.asyncio
    async def test_get_existing(self, tenant_repo, mock_pool):
        """get() 应返回存在的租户。"""
        now = datetime(2026, 7, 4, 12, 0, 0)
        mock_pool.fetchrow.return_value = {
            "id": "t-org1",
            "name": "组织一",
            "status": "active",
            "created_at": now,
        }

        result = await tenant_repo.get("t-org1")

        assert isinstance(result, Tenant)
        assert result.id == "t-org1"
        assert result.name == "组织一"
        mock_pool.fetchrow.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_missing_returns_none(self, tenant_repo, mock_pool):
        """get() 应在租户不存在时返回 None。"""
        mock_pool.fetchrow.return_value = None

        result = await tenant_repo.get("nonexistent")

        assert result is None


class TestTenantList:
    """PgTenantRepository.list() 测试。"""

    @pytest.mark.asyncio
    async def test_list_returns_all(self, tenant_repo, mock_pool):
        """list() 应返回全部租户，按 created_at 排序。"""
        now = datetime(2026, 7, 4, 12, 0, 0)
        later = datetime(2026, 7, 4, 13, 0, 0)
        mock_pool.fetch.return_value = [
            {"id": "t-a", "name": "A", "status": "active", "created_at": now},
            {"id": "t-b", "name": "B", "status": "disabled", "created_at": later},
        ]

        result = await tenant_repo.list()

        assert len(result) == 2
        assert result[0].id == "t-a"
        assert result[0].name == "A"
        assert result[1].id == "t-b"
        assert result[1].status == "disabled"
        mock_pool.fetch.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_list_empty(self, tenant_repo, mock_pool):
        """list() 应在无租户时返回空列表。"""
        mock_pool.fetch.return_value = []

        result = await tenant_repo.list()

        assert result == []


# ============================================================================
# PgApiKeyRepository
# ============================================================================


class TestApiKeyCreate:
    """PgApiKeyRepository.create() 测试。"""

    @pytest.mark.asyncio
    async def test_create_success(self, apikey_repo, mock_pool):
        """create() 应 INSERT api_keys 并返回 ApiKey 领域模型。"""
        now = datetime(2026, 7, 4, 12, 0, 0)
        mock_pool.fetchrow.return_value = {
            "id": "550e8400-e29b-41d4-a716-446655440000",
            "tenant_id": "t-org1",
            "key_hash": "abc123hash",
            "key_prefix": "rk_abcd",
            "name": "生产环境密钥",
            "status": "active",
            "expires_at": None,
            "created_at": now,
        }

        result = await apikey_repo.create(
            tenant_id="t-org1",
            key_hash="abc123hash",
            key_prefix="rk_abcd",
            name="生产环境密钥",
        )

        assert isinstance(result, ApiKey)
        assert result.id == "550e8400-e29b-41d4-a716-446655440000"
        assert result.tenant_id == "t-org1"
        assert result.key_hash == "abc123hash"
        assert result.key_prefix == "rk_abcd"
        assert result.name == "生产环境密钥"
        assert result.status == "active"
        assert result.expires_at is None
        mock_pool.fetchrow.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_create_with_expires_at(self, apikey_repo, mock_pool):
        """create() 应支持可选的 expires_at。"""
        now = datetime(2026, 7, 4, 12, 0, 0)
        expires = datetime(2027, 7, 4, 12, 0, 0)
        mock_pool.fetchrow.return_value = {
            "id": "uuid-1",
            "tenant_id": "t-org1",
            "key_hash": "hash1",
            "key_prefix": "rk_xx",
            "name": "有时限密钥",
            "status": "active",
            "expires_at": expires,
            "created_at": now,
        }

        result = await apikey_repo.create(
            tenant_id="t-org1",
            key_hash="hash1",
            key_prefix="rk_xx",
            name="有时限密钥",
            expires_at=expires,
        )

        assert result.expires_at == expires

    @pytest.mark.asyncio
    async def test_create_duplicate_hash_raises_conflict(self, apikey_repo, mock_pool):
        """create() 应在 key_hash 重复时抛出 ConflictError。"""
        mock_pool.fetchrow.side_effect = asyncpg.UniqueViolationError(
            "duplicate key value violates unique constraint"
        )

        with pytest.raises(AppError) as exc_info:
            await apikey_repo.create(
                tenant_id="t-org1",
                key_hash="duplicate_hash",
                key_prefix="rk_xx",
                name="重复密钥",
            )

        assert exc_info.value.message == "密钥哈希已存在"


class TestApiKeyGetByHash:
    """PgApiKeyRepository.get_by_hash() 测试。"""

    @pytest.mark.asyncio
    async def test_get_by_hash_existing(self, apikey_repo, mock_pool):
        """get_by_hash() 应返回 JOIN tenants 后的完整记录。"""
        mock_pool.fetchrow.return_value = {
            "key_id": "uuid-1",
            "tenant_id": "t-org1",
            "key_hash": "abc123hash",
            "key_prefix": "rk_abcd",
            "key_name": "生产环境密钥",
            "key_status": "active",
            "expires_at": None,
            "created_at": datetime(2026, 7, 4, 12, 0, 0),
            "tenant_name": "组织一",
            "tenant_status": "active",
        }

        result = await apikey_repo.get_by_hash("abc123hash")

        assert result is not None
        assert isinstance(result, dict)
        assert result["key_id"] == "uuid-1"
        assert result["tenant_id"] == "t-org1"
        assert result["tenant_name"] == "组织一"
        assert result["key_status"] == "active"
        assert result["tenant_status"] == "active"
        mock_pool.fetchrow.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_by_hash_missing_returns_none(self, apikey_repo, mock_pool):
        """get_by_hash() 应在 Key 不存在时返回 None。"""
        mock_pool.fetchrow.return_value = None

        result = await apikey_repo.get_by_hash("nonexistent_hash")

        assert result is None
