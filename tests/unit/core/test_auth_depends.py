"""Tests for make_get_current_tenant Depends factory — 8 校验场景。"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from ragnexus.core.auth import TenantContext, make_get_current_tenant
from ragnexus.core.errors import AppError, ErrorCode


# ---------------------------------------------------------------------------
# 辅助工厂：创建 get_current_tenant 并绑定 header
# ---------------------------------------------------------------------------


def _dep_factory(auth_enabled=True, api_key_repo_return=None):
    """快速创建 get_current_tenant 闭包。"""
    api_key_repo = AsyncMock()
    api_key_repo.get_by_hash.return_value = api_key_repo_return
    tenant_repo = AsyncMock()  # make_get_current_tenant 内部不使用 tenant_repo 直接查询
    fn = make_get_current_tenant(
        tenant_repo=tenant_repo,
        api_key_repo=api_key_repo,
        auth_enabled=auth_enabled,
    )
    return fn, api_key_repo


# ---------------------------------------------------------------------------
# 场景 1: auth_enabled=false → 返回占位 TenantContext
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_auth_disabled_returns_fallback():
    fn, _ = _dep_factory(auth_enabled=False)
    ctx = await fn(authorization=None)
    assert ctx.tenant_id == "default"
    assert ctx.tenant_name == "默认租户"
    assert ctx.key_id == "fallback"
    assert ctx.key_prefix == "none"


# ---------------------------------------------------------------------------
# 场景 2: Header 缺失 → AppError(UNAUTHORIZED)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_missing_header_raises_unauthorized():
    fn, _ = _dep_factory(auth_enabled=True)
    with pytest.raises(AppError) as exc_info:
        await fn(authorization=None)
    assert exc_info.value.code == ErrorCode.UNAUTHORIZED
    assert "Authorization" in exc_info.value.message


# ---------------------------------------------------------------------------
# 场景 3: Bearer 格式错误 → AppError(UNAUTHORIZED)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_bad_bearer_format_raises_unauthorized():
    fn, _ = _dep_factory(auth_enabled=True)
    with pytest.raises(AppError) as exc_info:
        await fn(authorization="Basic dXNlcjpwYXNz")
    assert exc_info.value.code == ErrorCode.UNAUTHORIZED
    assert "格式错误" in exc_info.value.message


# ---------------------------------------------------------------------------
# 场景 4: Key 不存在 (repo 返回 None) → AppError(UNAUTHORIZED)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_key_not_found_raises_unauthorized():
    fn, _ = _dep_factory(auth_enabled=True, api_key_repo_return=None)
    with pytest.raises(AppError) as exc_info:
        await fn(authorization="Bearer rk_nonexistent_key")
    assert exc_info.value.code == ErrorCode.UNAUTHORIZED
    assert "无效" in exc_info.value.message


# ---------------------------------------------------------------------------
# 场景 5: Key 已吊销 → AppError(UNAUTHORIZED)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_key_revoked_raises_unauthorized():
    fn, _ = _dep_factory(
        auth_enabled=True,
        api_key_repo_return={
            "key_id": "k1",
            "key_prefix": "rk_a1",
            "key_status": "revoked",
            "tenant_id": "t1",
            "tenant_name": "正式",
            "tenant_status": "active",
            "expires_at": None,
        },
    )
    with pytest.raises(AppError) as exc_info:
        await fn(authorization="Bearer rk_valid_format")
    assert exc_info.value.code == ErrorCode.UNAUTHORIZED
    assert "吊销" in exc_info.value.message


# ---------------------------------------------------------------------------
# 场景 6: Key 已过期 → AppError(UNAUTHORIZED)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_key_expired_raises_unauthorized():
    past = datetime.now(timezone.utc) - timedelta(days=1)
    fn, _ = _dep_factory(
        auth_enabled=True,
        api_key_repo_return={
            "key_id": "k2",
            "key_prefix": "rk_b2",
            "key_status": "active",
            "tenant_id": "t2",
            "tenant_name": "正式",
            "tenant_status": "active",
            "expires_at": past,
        },
    )
    with pytest.raises(AppError) as exc_info:
        await fn(authorization="Bearer rk_expired_key")
    assert exc_info.value.code == ErrorCode.UNAUTHORIZED
    assert "过期" in exc_info.value.message


# ---------------------------------------------------------------------------
# 场景 7: 租户已禁用 → AppError(UNAUTHORIZED)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_tenant_disabled_raises_unauthorized():
    future = datetime.now(timezone.utc) + timedelta(days=30)
    fn, _ = _dep_factory(
        auth_enabled=True,
        api_key_repo_return={
            "key_id": "k3",
            "key_prefix": "rk_c3",
            "key_status": "active",
            "tenant_id": "t3",
            "tenant_name": "冻结租户",
            "tenant_status": "disabled",
            "expires_at": future,
        },
    )
    with pytest.raises(AppError) as exc_info:
        await fn(authorization="Bearer rk_disabled_tenant")
    assert exc_info.value.code == ErrorCode.UNAUTHORIZED
    assert "禁用" in exc_info.value.message


# ---------------------------------------------------------------------------
# 场景 8: 正常流程 → 返回正确 TenantContext
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_normal_flow_returns_tenant_context():
    future = datetime.now(timezone.utc) + timedelta(days=30)
    api_key_repo_return = {
        "key_id": "k4",
        "key_prefix": "rk_d4",
        "key_status": "active",
        "tenant_id": "t4",
        "tenant_name": "正式租户",
        "tenant_status": "active",
        "expires_at": future,
    }
    fn, repo_mock = _dep_factory(
        auth_enabled=True,
        api_key_repo_return=api_key_repo_return,
    )

    ctx = await fn(authorization="Bearer rk_valid_real_key")

    # 验证 Context 字段
    assert isinstance(ctx, TenantContext)
    assert ctx.tenant_id == "t4"
    assert ctx.tenant_name == "正式租户"
    assert ctx.key_id == "k4"
    assert ctx.key_prefix == "rk_d4"

    # 验证 repo 被调用了（通过 token 的哈希）
    repo_mock.get_by_hash.assert_awaited_once()
