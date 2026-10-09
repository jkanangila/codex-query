from __future__ import annotations

import logging
from typing import override

from codex_query.application.ports.logger import LoggerRepositoryPort


class PythonLogger(LoggerRepositoryPort):
    """ILogger implementation backed by Python's logging package."""

    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger

    @override
    def debug(self, message: str, *args: object) -> None:
        self._logger.debug(message, *args)

    @override
    def info(self, message: str, *args: object) -> None:
        self._logger.info(message, *args)

    @override
    def warning(self, message: str, *args: object) -> None:
        self._logger.warning(message, *args)

    @override
    def error(self, message: str, *args: object) -> None:
        self._logger.error(message, *args)

    @override
    def exception(self, message: str, *args: object) -> None:
        self._logger.exception(message, *args)

    @override
    def critical(self, message: str, *args: object) -> None:
        self._logger.critical(message, *args)
