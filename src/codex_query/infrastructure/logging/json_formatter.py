import json
import sys
from datetime import UTC, datetime
from logging import Formatter, LogRecord
from typing import Final, override

# Pre-compute standard LogRecord fields to avoid re-instantiating on every log call.
_STANDARD_LOG_FIELDS: Final[frozenset[str]] = frozenset(
    LogRecord(
        name="",
        level=0,
        pathname="",
        lineno=0,
        msg="",
        args=(),
        exc_info=None,
    ).__dict__.keys()
)


class JsonFormatter(Formatter):
    """Custom logging formatter that outputs log records as JSON strings.

    Formats standard log metadata, exception information, stack traces,
    and extra user-defined attributes into a structured JSON payload.
    """

    @staticmethod
    def _serialize(value: object) -> object:
        """Convert arbitrary values into JSON-compatible types.

        Falls back to ``repr(value)`` if the value cannot be serialized directly.

        Args:
            value: The object to serialize.

        Returns:
            The original value if JSON serializable, or its string representation.
        """
        try:
            json.dumps(value)
        except (TypeError, ValueError):
            return repr(value)

        return value

    @override
    def format(self, record: LogRecord) -> str:
        """Format the specified log record as a JSON string.

        Args:
            record: The Python logging record to format.

        Returns:
            A JSON-encoded string representation of the log payload.
        """
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(
                record.created,
                tz=UTC,
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        if record.exc_info:
            if isinstance(record.exc_info, tuple):  # pyright: ignore[reportUnnecessaryIsInstance]
                payload["exception"] = self.formatException(record.exc_info)
            else:
                payload["exception"] = self.formatException(sys.exc_info())

        if record.stack_info is not None:
            payload["stack"] = self.formatStack(record.stack_info)

        for key, val in record.__dict__.items():
            value: object = val
            if key.startswith("_") or key in _STANDARD_LOG_FIELDS:
                continue

            payload[key] = self._serialize(value)

        return json.dumps(
            payload,
            ensure_ascii=False,
            default=repr,
        )
