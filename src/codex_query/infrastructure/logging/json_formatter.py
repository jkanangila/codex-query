import json
from datetime import UTC, datetime
from logging import Formatter, LogRecord
from typing import override


class JsonFormatter(Formatter):
    @staticmethod
    def _serialize(value: object) -> object:
        """Convert arbitrary values into JSON-compatible values."""
        try:
            json.dumps(value)
        except (TypeError, ValueError):
            return repr(value)

        return value

    @override
    def format(self, record: LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(
                record.created,
                tz=UTC,
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        if record.exc_info is not None:
            payload["exception"] = self.formatException(record.exc_info)

        if record.stack_info is not None:
            payload["stack"] = self.formatStack(record.stack_info)

        standard_fields: set[str] = set(
            LogRecord(
                name="",
                level=0,
                pathname="",
                lineno=0,
                msg="",
                args=(),
                exc_info=None,
            ).__dict__
        )

        for key, value in record.__dict__.items():
            if key.startswith("_") or key in standard_fields:
                continue

            payload[key] = self._serialize(value)

        return json.dumps(
            payload,
            ensure_ascii=False,
            default=repr,
        )
