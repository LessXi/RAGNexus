"""E2E test configuration — provides a real FastAPI TestClient wired to test-db."""

import asyncio
import os

import asyncpg
import pytest
from fastapi.testclient import TestClient

from ragnexus.composition import build_app
from ragnexus.config import get_settings
from tests.conftest import _docker_available

TEST_DSN = "postgresql://ragnexus:ragnexus@localhost:5433/ragnexus_test"

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not _docker_available(), reason="Docker not available"),
]


@pytest.fixture(autouse=True)
def _require_test_db():
    try:

        async def _check():
            conn = await asyncpg.connect(TEST_DSN, timeout=2)
            await conn.close()

        asyncio.run(asyncio.wait_for(_check(), timeout=5))
    except Exception:
        pytest.skip("测试数据库不可用（Docker Compose 未启动）")


@pytest.fixture(scope="module")
def client(_apply_schema, ensure_test_db):
    """Return a TestClient with the real app wired to the test DB.

    The ``_apply_schema`` dependency ensures tables exist before the app starts;
    ``ensure_test_db`` ensures Docker Compose is running.
    """
    os.environ["PG_DSN"] = TEST_DSN
    os.environ["PG_POOL_MIN"] = "1"
    os.environ["PG_POOL_MAX"] = "3"
    os.environ["PG_COMMAND_TIMEOUT"] = "15"
    get_settings.cache_clear()

    app = build_app()
    with TestClient(app) as c:
        yield c
