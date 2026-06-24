"""Top-level test configuration — manages test-db Docker Compose lifecycle.

Integration tests create their own asyncpg pools on pytest-asyncio's loop.
The conftest only handles Docker Compose start/stop.
"""

import subprocess
import sys
from pathlib import Path

import pytest

COMPOSE_FILE = Path(__file__).parent.parent / "docker-compose.test.yml"
TEST_DSN = "postgresql://ragnexus:ragnexus@localhost:5433/ragnexus_test"

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


def _start_compose() -> None:
    """Lazy-start Docker Compose for test-db if not already running."""
    global _compose_started
    if _compose_started:
        return
    if not _docker_available():
        print("[conftest] Docker not available — skipping compose", file=sys.stderr)
        return

    try:
        subprocess.run(
            ["docker", "compose", "-f", str(COMPOSE_FILE), "up", "-d", "test-db", "test-init"],
            check=True,
            capture_output=True,
            timeout=120,
        )
        _compose_started = True
    except Exception as exc:
        print(f"[conftest] compose start failed: {exc}", file=sys.stderr)


def _stop_compose() -> None:
    """Tear down Docker Compose if we started it."""
    global _compose_started
    if _compose_started:
        subprocess.run(
            ["docker", "compose", "-f", str(COMPOSE_FILE), "down", "-v"],
            capture_output=True,
            timeout=60,
        )
        _compose_started = False


def pytest_sessionfinish(session, exitstatus) -> None:
    _stop_compose()


@pytest.fixture(scope="session")
def ensure_test_db() -> None:
    """Start Docker Compose if not already running. No pool — tests create their own."""
    _start_compose()
    if not _compose_started:
        pytest.skip("Docker not available — integration/E2E tests require Docker Compose")
