"""Application entry point — run with ``uv run python main.py``.

Uses uvicorn's factory pattern::

    uvicorn.run("ragnexus.composition:build_app", factory=True, ...)

The ``build_app`` callable returns a fully-wired ``FastAPI`` instance.
"""

import uvicorn

from ragnexus.config import get_settings


def main() -> None:
    """Load settings and start the ASGI server."""
    cfg = get_settings()
    uvicorn.run(
        "ragnexus.composition:build_app",
        factory=True,
        host=cfg.HOST,
        port=cfg.PORT,
        log_level=cfg.LOG_LEVEL.lower(),
    )


if __name__ == "__main__":
    main()
