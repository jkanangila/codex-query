from __future__ import annotations

import asyncio
import logging
import logging.handlers
import os
import sys
from pathlib import Path
from types import TracebackType
from typing import Any, Final

from codex_query.infrastructure.paths import AppPaths

from .json_formatter import JsonFormatter

LOG_FORMAT: Final[str] = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
DATE_FORMAT: Final[str] = "%Y-%m-%d %H:%M:%S"

log = logging.getLogger(__name__)


def log_dir() -> Path:
    root = AppPaths.app_storage_data_dir()
    path = root / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


file_handler = logging.handlers.RotatingFileHandler(
    log_dir() / "codex.jsonl",
    maxBytes=1_000_000,
    backupCount=3,
    encoding="utf-8",
)
file_handler.setFormatter(JsonFormatter())


def _configure_development_logging(level: int | str = logging.DEBUG) -> None:
    """Configure human-readable logging for local development."""
    handler = logging.StreamHandler(sys.stdout)

    handler.setFormatter(
        logging.Formatter(
            fmt=LOG_FORMAT,
            datefmt=DATE_FORMAT,
        )
    )
    logging.basicConfig(
        level=level,
        handlers=[
            handler,
            file_handler,
        ],
        force=True,
    )


def _configure_production_logging(level: int | str = logging.INFO) -> None:
    """Configure structured JSON logging for production."""
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(logging.INFO)
    stdout_handler.setFormatter(JsonFormatter())

    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setLevel(logging.ERROR)
    stderr_handler.setFormatter(JsonFormatter())

    logging.basicConfig(
        level=level,
        handlers=[
            stdout_handler,
            stderr_handler,
            file_handler,
        ],
        force=True,
    )


def configure_logging() -> None:
    """Configure application-wide logging."""
    level: int | str = os.getenv("LOG_LEVEL", "info").upper()

    try:
        assert level in logging._levelToName.values()  # pyright: ignore[reportPrivateUsage]
    except AssertionError:
        log.warning("Incorrect value passed for log_level. Setting it to INFO")
        level = logging.INFO

    environment = os.getenv("ENVIRONMENT", "production")

    if environment == "development":
        _configure_development_logging(level)
    else:
        _configure_production_logging(level)

    for noisy in ("sqlalchemy.engine", "httpx", "httpcore", "aiosqlite"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    sys.excepthook = _excepthook


def _excepthook(
    exc_type: type[BaseException],
    exc: BaseException,
    tb: TracebackType | None,
) -> None:
    log.critical("Uncaught exception", exc_info=(exc_type, exc, tb))


def asyncio_handler(loop: asyncio.AbstractEventLoop, ctx: dict[str, Any]) -> None:
    log.error("Asyncio error: %s", ctx.get("message"), exc_info=ctx.get("exception"))
