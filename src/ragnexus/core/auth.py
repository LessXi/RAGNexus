"""鉴权核心——TenantContext 上下文 + 纯函数（SHA-256 哈希、Bearer 令牌解析）。

本模块提供无副作用的纯函数，不依赖数据库或外部服务。
Depends 工厂函数见同文件后续追加（Task 1.5b）。
"""

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import Header

from ragnexus.core.errors import AppError, ErrorCode


@dataclass
class TenantContext:
    """鉴权通过后的租户上下文，注入到每个请求中。

    字段：
    - tenant_id: 租户唯一标识
    - tenant_name: 租户展示名
    - key_id: 本次鉴权使用的 API Key UUID
    - key_prefix: Key 前缀（如 "rk_a1b2"），日志辨认用
    """

    tenant_id: str
    tenant_name: str
    key_id: str
    key_prefix: str
    plan: str = "free"  # 租户套餐: free | standard | pro


def hash_key(raw_key: str) -> str:
    """对原始 API Key 做 SHA-256 哈希，返回十六进制字符串。"""
    return hashlib.sha256(raw_key.encode()).hexdigest()


def extract_token(header: str | None) -> str | None:
    """从 Authorization: Bearer xxx 中提取 token。

    返回 None 的情况：
    - header 为 None 或空
    - 格式不是 "Bearer <token>"（两个空格分隔的单词，第一个小写为 bearer）
    """
    if not header:
        return None
    parts = header.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1]


_FALLBACK_TENANT = TenantContext(
    tenant_id="default",
    tenant_name="默认租户",
    key_id="fallback",
    key_prefix="none",
    plan="pro",  # AUTH_ENABLED=false 时享有全部功能
)


def make_get_current_tenant(
    tenant_repo,  # PgTenantRepository
    api_key_repo,  # PgApiKeyRepository
    auth_enabled: bool,
):
    """创建 FastAPI Depends 工厂——闭包注入仓库和配置。

    校验流程：
    1. AUTH_ENABLED=false → 返回占位 TenantContext
    2. Authorization Header 缺失 → 401 UNAUTHORIZED
    3. Bearer 格式错误 → 401 UNAUTHORIZED
    4. Key 不存在 → 401 UNAUTHORIZED
    5. Key 已吊销 → 401 UNAUTHORIZED
    6. Key 已过期 → 401 UNAUTHORIZED
    7. 租户已禁用 → 401 UNAUTHORIZED
    8. 正常 → 返回 TenantContext
    """

    async def get_current_tenant(
        authorization: str | None = Header(None),
    ) -> TenantContext:
        # 1. 降级模式
        if not auth_enabled:
            return _FALLBACK_TENANT

        # 2. Header 缺失
        if authorization is None:
            raise AppError(
                ErrorCode.UNAUTHORIZED,
                "缺少 Authorization 请求头",
            )

        # 3. Bearer 格式校验
        token = extract_token(authorization)
        if token is None:
            raise AppError(
                ErrorCode.UNAUTHORIZED,
                "Authorization 格式错误，应为 Bearer <api_key>",
            )

        # 4. Key 哈希查询
        key_hash = hash_key(token)
        key_record = await api_key_repo.get_by_hash(key_hash)
        if key_record is None:
            raise AppError(
                ErrorCode.UNAUTHORIZED,
                "API Key 无效",
            )

        # 5. Key 已吊销
        if key_record["key_status"] == "revoked":
            raise AppError(
                ErrorCode.UNAUTHORIZED,
                "API Key 已被吊销",
            )

        # 6. Key 已过期
        expires_at = key_record.get("expires_at")
        if expires_at is not None and expires_at < datetime.now(UTC):
            raise AppError(
                ErrorCode.UNAUTHORIZED,
                "API Key 已过期",
            )

        # 7. 租户已禁用
        if key_record["tenant_status"] == "disabled":
            raise AppError(
                ErrorCode.UNAUTHORIZED,
                "租户已被禁用",
            )

        # 8. 正常返回
        return TenantContext(
            tenant_id=key_record["tenant_id"],
            tenant_name=key_record["tenant_name"],
            key_id=key_record["key_id"],
            key_prefix=key_record["key_prefix"],
            plan=key_record.get("tenant_plan", "free"),
        )

    return get_current_tenant
