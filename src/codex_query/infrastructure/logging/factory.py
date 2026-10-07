from __future__ import annotations

import logging

from codex_query.application.ports.logger import ILogger
from codex_query.infrastructure.logging.python_logger import PythonLogger


def create_logger(name: str) -> ILogger:
    """Create an application logger."""

    return PythonLogger(logging.getLogger(name))
