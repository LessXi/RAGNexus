#!/usr/bin/env python
"""verify-production.py — 生产环境验收。

用法: python scripts/verify-production.py
"""

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
os.chdir(PROJECT_DIR)
PY = sys.executable


def step(n, total, desc):
    print(f"\n[{n}/{total}] {desc}…")


def run(cmd, **kw):
    print(f"  → {' '.join(cmd[:6])}{'...' if len(cmd) > 6 else ''}")
    return subprocess.run(cmd, check=True, **kw)


def main():
    print("=" * 60)
    print(f"  RAGNexus 生产环境验证  {datetime.now():%Y-%m-%d %H:%M:%S}")
    print("=" * 60)

    step(1, 4, "加载 API key")
    from ragnexus.config import get_settings

    s = get_settings()
    if not s.EMBED_API_KEY or not s.LLM_API_KEY:
        print("  ❌ API key 未配置")
        sys.exit(1)
    os.environ.setdefault("EMBED_API_KEY", s.EMBED_API_KEY)
    os.environ.setdefault("LLM_API_KEY", s.LLM_API_KEY)
    print("  ✓ 已加载")

    step(2, 4, "数据库就绪 + 迁移")
    # Docker 已在运行时跳过 compose start
    result = subprocess.run(
        ["docker", "compose", "-f", "docker-compose.test.yml", "ps", "-q"],
        capture_output=True,
        text=True,
    )
    if not result.stdout.strip():
        run(
            [
                "docker",
                "compose",
                "-f",
                "docker-compose.test.yml",
                "up",
                "-d",
                "--wait",
            ],
            capture_output=True,
        )
    else:
        print("  → 数据库已在运行")
    os.environ.setdefault(
        "PG_DSN", "postgresql://ragnexus:ragnexus@localhost:5433/ragnexus_test"
    )
    run([PY, "-m", "alembic", "upgrade", "head"])
    print("  ✓ 就绪")

    step(3, 4, "全量测试")
    for cmd in [
        [
            PY,
            "-m",
            "pytest",
            "tests/",
            "--ignore=tests/unit/adapters/test_middleware.py",
            "-q",
        ],
        [PY, "-m", "pytest", "tests/unit/adapters/test_middleware.py", "-q"],
        [PY, "-m", "pytest", "tests/e2e/", "-q"],
    ]:
        run(cmd)

    step(4, 4, "覆盖率")
    subprocess.run(
        [
            PY,
            "-m",
            "pytest",
            "tests/",
            "--cov=src/ragnexus",
            "--cov-report=term",
            "-q",
            "--ignore=tests/unit/adapters/test_middleware.py",
        ]
    )

    print("\n" + "=" * 60)
    print("  ✅ 验证通过")
    print("=" * 60)


if __name__ == "__main__":
    main()
