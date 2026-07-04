"""生成 API Key——为指定租户生成 Key 并存入数据库。

用法：
    uv run python scripts/create_api_key.py --tenant-id my_tenant --name "生产环境"

注意：Key 仅在终端打印一次，请妥善保存！
"""

from __future__ import annotations

import argparse
import asyncio
import secrets
import sys
from datetime import datetime, timedelta
from pathlib import Path

import asyncpg

# 将项目 src 目录加入 sys.path，以便导入 ragnexus 模块
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ragnexus.config import get_settings  # noqa: E402
from ragnexus.core.auth import hash_key  # noqa: E402
from ragnexus.core.errors import AppError, ErrorCode  # noqa: E402

# Key 格式前缀
_KEY_PREFIX = "rk_live_"


async def _create_api_key(
    tenant_id: str,
    key_name: str,
    expires_in_days: int | None,
) -> tuple[str, str]:
    """为指定租户生成 API Key，返回原始 Key。

    Raises:
        AppError: 租户不存在。
    """
    settings = get_settings()
    conn = await asyncpg.connect(settings.PG_DSN)
    try:
        # 检查租户是否存在
        tenant = await conn.fetchrow(
            "SELECT id, name FROM tenants WHERE id = $1", tenant_id
        )
        if tenant is None:
            raise AppError(
                ErrorCode.NOT_FOUND,
                f"租户 '{tenant_id}' 不存在",
            )

        # 生成 Key
        raw_key = _KEY_PREFIX + secrets.token_hex(32)
        key_prefix = "rk_" + raw_key[8:12]  # rk_live_ 后取 4 字符
        key_hash = hash_key(raw_key)

        # 计算过期时间
        expires_at: datetime | None = None
        if expires_in_days:
            expires_at = datetime.now(datetime.UTC) + timedelta(days=expires_in_days)

        # 存入数据库
        await conn.execute(
            """INSERT INTO api_keys (tenant_id, key_hash, key_prefix, name, expires_at)
               VALUES ($1, $2, $3, $4, $5)""",
            tenant_id,
            key_hash,
            key_prefix,
            key_name,
            expires_at,
        )

        return raw_key, tenant["name"]
    finally:
        await conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="生成 API Key")
    parser.add_argument("--tenant-id", required=True, help="所属租户 ID")
    parser.add_argument("--name", required=True, help="Key 名称")
    parser.add_argument("--expires-in-days", type=int, default=None, help="过期天数")
    args = parser.parse_args()

    try:
        raw_key, tenant_name = asyncio.run(
            _create_api_key(args.tenant_id, args.name, args.expires_in_days)
        )
    except AppError as e:
        print(f"错误 [{e.code}]: {e.message}", file=sys.stderr)
        sys.exit(1)

    print("\nAPI Key 已生成（仅显示一次，请妥善保存！）")
    print(f"租户：{tenant_name} ({args.tenant_id})")
    print(f"Key：{raw_key}\n")


if __name__ == "__main__":
    main()
