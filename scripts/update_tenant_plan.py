"""修改租户套餐 — CLI 运维脚本。

用法：
    PG_DSN="postgresql://..." uv run python scripts/update_tenant_plan.py \\
        --tenant-id my_tenant \\
        --plan standard

有效 plan: free, standard, pro
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

import asyncpg

VALID_PLANS = {"free", "standard", "pro"}


async def main() -> None:
    parser = argparse.ArgumentParser(description="修改租户套餐")
    parser.add_argument("--tenant-id", required=True, help="租户唯一标识")
    parser.add_argument(
        "--plan",
        required=True,
        choices=sorted(VALID_PLANS),
        help="目标套餐: free | standard | pro",
    )
    args = parser.parse_args()

    dsn = os.environ.get(
        "PG_DSN",
        "postgresql://ragnexus:ragnexus@localhost:5432/ragnexus",
    )
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=1)
    try:
        exists = await pool.fetchval(
            "SELECT 1 FROM tenants WHERE id=$1", args.tenant_id
        )
        if not exists:
            print(f"错误: 租户 {args.tenant_id} 不存在", file=sys.stderr)
            sys.exit(1)
        await pool.execute(
            "UPDATE tenants SET plan=$1 WHERE id=$2",
            args.plan,
            args.tenant_id,
        )
        print(f"租户 plan 已更新: id={args.tenant_id} plan={args.plan}")
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
