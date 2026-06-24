"""Top-level test configuration — manages test-db Docker Compose lifecycle."""

import asyncio
import subprocess
import sys
from pathlib import Path

import asyncpg
import pytest

COMPOSE_FILE = Path(__file__).parent.parent / "docker-compose.test.yml"
TEST_DSN = "postgresql://ragnexus:ragnexus@localhost:5433/ragnexus_test"

_pool: asyncpg.Pool | None = None
_loop: asyncio.AbstractEventLoop | None = None
_compose_started = False


def _docker_available() -> bool:
    try:
        return (
            subprocess.run(
                ["docker", "compose", "version"],
                capture_output=True,
                text=True,
                timeout=10,
            ).returncode
            == 0
        )
    except Exception:
        return False


async def _wait_for_db(dsn: str, timeout: int = 60) -> None:
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
            await asyncio.sleep(1)
    msg = f"Test DB not ready after {timeout}s"
    if last_err:
        msg += f": {last_err}"
    raise RuntimeError(msg)


def _start_compose() -> None:
    """Lazy-start Docker Compose for test-db if not already running."""
    global _pool, _loop, _compose_started
    if _compose_started or _pool is not None:
        return
    if not _docker_available():
        print("[conftest] Docker not available — skipping compose", file=sys.stderr)
        return

    try:
        subprocess.run(
            ["docker", "compose", "-f", str(COMPOSE_FILE), "up", "-d", "test-db", "test-init"],
            check=True, capture_output=True, timeout=120,
        )
        _compose_started = True
    except Exception as exc:
        print(f"[conftest] compose start failed: {exc}", file=sys.stderr)
        return

    _loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_loop)
    try:
        _loop.run_until_complete(_wait_for_db(TEST_DSN))
        _pool = _loop.run_until_complete(
            asyncpg.create_pool(TEST_DSN, min_size=1, max_size=5, command_timeout=15)
        )
    except Exception as exc:
        print(f"[conftest] DB connection failed: {exc}", file=sys.stderr)
        _pool = None


def _stop_compose() -> None:
    global _pool, _loop, _compose_started
    if _pool is not None and _loop is not None:
        try:
            _loop.run_until_complete(_pool.close())
        except Exception:
            pass
        _pool = None
    if _loop is not None:
        try:
            _loop.close()
        except Exception:
            pass
        _loop = None
    if _compose_started:
        subprocess.run(
            ["docker", "compose", "-f", str(COMPOSE_FILE), "down", "-v"],
            capture_output=True, timeout=60,
        )
        _compose_started = False


def pytest_sessionstart(session) -> None:
    pass


def pytest_sessionfinish(session, exitstatus) -> None:
    _stop_compose()


@pytest.fixture(scope="session")
def pg_pool() -> asyncpg.Pool:
    _start_compose()
    if _pool is None:
        pytest.skip("Docker not available — integration/E2E tests require Docker Compose")
    return _pool
