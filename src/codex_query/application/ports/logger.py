from __future__ import annotations

from typing import Protocol


class LoggerRepositoryPort(Protocol):
    """Application-facing logging abstraction."""

    def debug(self, message: str, *args: object) -> None:
        """Log a debug-level message."""

    def info(self, message: str, *args: object) -> None:
        """Log an informational message."""

    def warning(self, message: str, *args: object) -> None:
        """Log a warning message."""

    def error(self, message: str, *args: object) -> None:
        """Log an error message."""

    def exception(self, message: str, *args: object) -> None:
        """Log an error message including the current exception."""

    def critical(self, message: str, *args: object) -> None:
        """Log a critical error."""


class LoggerFactoryPort(Protocol):
    def create(self, name: str) -> LoggerRepositoryPort: ...
