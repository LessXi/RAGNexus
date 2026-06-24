"""E2E test configuration — provides a real FastAPI TestClient wired to test-db."""

import os

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


@pytest.fixture(scope="module")
def client(ensure_test_db):
    """Return a TestClient with the real app wired to the test DB.

    The ``ensure_test_db`` dependency ensures Docker Compose is running before
    the app attempts to connect to the test database.
    """
    # Override PG_DSN to point at test-db (port 5433)
    os.environ["PG_DSN"] = TEST_DSN
    os.environ["PG_POOL_MIN"] = "1"
    os.environ["PG_POOL_MAX"] = "3"
    os.environ["PG_COMMAND_TIMEOUT"] = "15"
    get_settings.cache_clear()

    app = build_app()
    with TestClient(app) as c:
        yield c
