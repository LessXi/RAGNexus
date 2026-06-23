"""Top-level test configuration — manages test-db Docker Compose lifecycle."""

import asyncio
import subprocess
from pathlib import Path

import asyncpg
import pytest

COMPOSE_FILE = Path(__file__).parent / "docker-compose.test.yml"
TEST_DSN = "postgresql://ragnexus:ragnexus@localhost:5433/ragnexus_test"

_pool: asyncpg.Pool | None = None
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
    global _pool, _compose_started
    if _compose_started or _pool is not None:
        return
    if not _docker_available():
        return

    try:
        subprocess.run(
            [
                "docker",
                "compose",
                "-f",
                str(COMPOSE_FILE),
                "up",
                "-d",
                "test-db",
                "test-init",
            ],
            check=True,
            capture_output=True,
            timeout=120,
        )
        _compose_started = True
    except Exception:
        return  # compose failed — tests will skip via pg_pool fixture being None

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_wait_for_db(TEST_DSN))
        _pool = loop.run_until_complete(
            asyncpg.create_pool(
                TEST_DSN, min_size=1, max_size=5, command_timeout=15
            )
        )
    except Exception:
        _pool = None  # connection failed — tests skip gracefully
    finally:
        loop.close()


def _stop_compose() -> None:
    global _pool, _compose_started
    if _pool is not None:
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_pool.close())
        finally:
            loop.close()
        _pool = None
    if _compose_started:
        subprocess.run(
            ["docker", "compose", "-f", str(COMPOSE_FILE), "down", "-v"],
            capture_output=True,
            timeout=60,
        )
        _compose_started = False


def pytest_sessionstart(session) -> None:
    """Session start is a no-op — compose starts lazily via pg_pool fixture."""


def pytest_sessionfinish(session, exitstatus) -> None:
    """Clean up compose containers at session end."""
    _stop_compose()


@pytest.fixture(scope="session")
def pg_pool() -> asyncpg.Pool:
    """Return a session-scoped asyncpg pool for the test DB.

    Starts Docker Compose on first use if Docker is available.
    Skips the calling test if Docker is not available.
    """
    _start_compose()
    if _pool is None:
        pytest.skip("Docker not available — integration/E2E tests require Docker Compose")
    return _pool
