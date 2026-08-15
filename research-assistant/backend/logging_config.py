import json
import logging
import sys
from datetime import datetime, timezone

# Fields every Python LogRecord has by default — anything else passed via
# logger.info(..., extra={...}) is application-specific and gets folded
# into the JSON output automatically.
_STANDARD_FIELDS = set(logging.LogRecord(
    name="", level=0, pathname="", lineno=0, msg="", args=(), exc_info=None
).__dict__.keys())


class JsonFormatter(logging.Formatter):
    """Emits one JSON object per log line — the format real log aggregators
    (CloudWatch, Datadog, Loki, etc.) expect, instead of plain text that
    has to be parsed with regexes at query time."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        extras = {
            key: value for key, value in record.__dict__.items()
            if key not in _STANDARD_FIELDS and not key.startswith("_")
        }
        if extras:
            payload["extra"] = extras

        return json.dumps(payload, default=str)


def configure_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(handler)
