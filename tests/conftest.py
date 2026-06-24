"""Top-level test configuration — manages test-db Docker Compose lifecycle."""

import asyncio
import subprocess
import sys
from pathlib import Path

import asyncpg
import nest_asyncio
import pytest
import pytest_asyncio

nest_asyncio.apply()

COMPOSE_FILE = Path(__file__).parent.parent / "docker-compose.test.yml"
TEST_DSN = "postgresql://ragnexus:ragnexus@localhost:5433/ragnexus_test"

_compose_started = False


def _docker_available() -> bool:
    try:
        return (
            subprocess.run(
                ["docker", "compose", "version"],
                capture_output=True, text=True, timeout=10,
            ).returncode == 0
        )
    except Exception:
        return False


def _start_compose() -> None:
    global _compose_started
    if _compose_started:
        return
    if not _docker_available():
        return

    try:
        subprocess.run(
            ["docker", "compose", "-f", str(COMPOSE_FILE), "up", "-d", "test-db", "test-init"],
            check=True, capture_output=True, timeout=120,
        )
        _compose_started = True
    except Exception as exc:
        print(f"[conftest] compose start failed: {exc}", file=sys.stderr)


def _stop_compose() -> None:
    global _compose_started
    if _compose_started:
        subprocess.run(
            ["docker", "compose", "-f", str(COMPOSE_FILE), "down", "-v"],
            capture_output=True, timeout=60,
        )
        _compose_started = False


@pytest_asyncio.fixture(scope="session")
async def event_loop():
    """Session-scoped event loop shared by all async fixtures and tests."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def pg_pool(event_loop) -> asyncpg.Pool:
    """Session-scoped asyncpg pool for test DB. Starts Docker Compose lazily."""
    _start_compose()
    if not _docker_available():
        pytest.skip("Docker not available")

    import time
    start = time.monotonic()
    while time.monotonic() - start < 60:
        try:
            conn = await asyncpg.connect(TEST_DSN, timeout=2)
            await conn.close()
            break
        except Exception:
            await asyncio.sleep(1)
    else:
        pytest.skip("Test DB not ready after 60s")

    pool = await asyncpg.create_pool(TEST_DSN, min_size=1, max_size=5, command_timeout=15)
    yield pool
    await pool.close()
    _stop_compose()


def pytest_sessionfinish(session, exitstatus) -> None:
    _stop_compose()
