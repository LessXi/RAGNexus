"""Integration test fixtures — per-test asyncpg pools on pytest-asyncio's loop."""

import asyncio
from collections.abc import AsyncIterator

import asyncpg
import pytest_asyncio

TEST_DSN = "postgresql://ragnexus:ragnexus@localhost:5433/ragnexus_test"


async def _wait_for_db(dsn: str, timeout: int = 30) -> None:
    """Block until the test DB accepts connections."""
    import time

    start = time.monotonic()
    last_err = None
    while time.monotonic() - start < timeout:
        try:
            conn = await asyncpg.connect(dsn, timeout=2)
            await conn.close()
            return
        except Exception as e:
            last_err = e
            await asyncio.sleep(0.5)
    msg = f"Test DB not ready after {timeout}s"
    if last_err:
        msg += f": {last_err}"
    raise RuntimeError(msg)


@pytest_asyncio.fixture
async def pg_pool(_apply_schema) -> AsyncIterator[asyncpg.Pool]:
    """Per-test asyncpg pool — fresh pool on pytest-asyncio's loop each test.

    Depends on root conftest's ``_apply_schema`` (session-scoped).
    """
    await _wait_for_db(TEST_DSN)
    pool = await asyncpg.create_pool(
        TEST_DSN,
        min_size=1,
        max_size=3,
        command_timeout=15,
    )
    yield pool
    await pool.close()
