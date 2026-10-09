from __future__ import annotations

import logging
from typing import override

from codex_query.application.ports.logger import LoggerFactoryPort, LoggerRepositoryPort
from codex_query.infrastructure.logging.python_logger import PythonLogger


def create_logger(name: str) -> LoggerRepositoryPort:
    """Create an application logger."""

    return PythonLogger(logging.getLogger(name))


class PythonLoggerFactory(LoggerFactoryPort):
    @override
    def create(self, name: str) -> LoggerRepositoryPort:
        return PythonLogger(logging.getLogger(name))
