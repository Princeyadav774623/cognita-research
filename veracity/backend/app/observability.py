"""Knowing what the service is doing.

Two things, and they answer different questions. Structured logs answer "what
happened to *this* request" — which means every line emitted while handling a
request has to carry the request's identity, or you are left grepping timestamps
and hoping. Metrics answer "what is happening in aggregate" — which is the
question you have during an incident, when reading logs is too slow.

Both are cheap to add now and impossible to add retrospectively during the
incident that makes you want them.
"""
from __future__ import annotations

import contextvars
import json
import logging
import time
import uuid
from typing import Any

# Carried on a ContextVar so a log line emitted five frames deep still knows
# which request it belongs to, without every function taking a context argument.
request_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None)
user_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "log_user_id", default=None)
job_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "log_job_id", default=None)


class ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id.get()
        record.user_id = user_id.get()
        record.job_id = job_id.get()
        return True


class JsonFormatter(logging.Formatter):
    """One JSON object per line.

    Human-readable logs are pleasant locally and useless in aggregate: you
    cannot filter "every error for this user in the last hour" out of prose.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created))
                  + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in ("request_id", "user_id", "job_id"):
            value = getattr(record, field, None)
            if value:
                payload[field] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure(level: str = "INFO", *, json_logs: bool = True) -> None:
    handler = logging.StreamHandler()
    handler.addFilter(ContextFilter())
    handler.setFormatter(
        JsonFormatter() if json_logs
        else logging.Formatter(
            "%(asctime)s %(levelname)-7s %(name)-18s %(message)s")
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    # These two narrate every request and every statement respectively, and
    # drown everything worth reading.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


def new_request_id() -> str:
    return uuid.uuid4().hex[:16]


# --------------------------------------------------------------------- metrics
class _Metrics:
    """A tiny in-process registry, exported in Prometheus text format.

    Deliberately not the prometheus_client library: the only thing needed here
    is counters and histograms over a handful of series, and the library's
    multiprocess mode — which is what a multi-worker uvicorn actually requires —
    brings a shared directory and a collector process with it. When this needs
    real cardinality it should be swapped wholesale rather than grown.

    The caveat that matters: with several uvicorn workers each holds its own
    counts, so a scrape hits one of them. Run one worker per container and let
    the orchestrator scale, or put a real exporter in front.
    """

    BUCKETS = (0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 300)

    def __init__(self) -> None:
        self._counters: dict[tuple, float] = {}
        self._hist: dict[tuple, list[float]] = {}
        self._help: dict[str, str] = {}

    def count(self, name: str, help_text: str = "", **labels: str) -> None:
        self._help.setdefault(name, help_text)
        key = (name, tuple(sorted(labels.items())))
        self._counters[key] = self._counters.get(key, 0.0) + 1

    def observe(self, name: str, seconds: float, help_text: str = "",
                **labels: str) -> None:
        self._help.setdefault(name, help_text)
        key = (name, tuple(sorted(labels.items())))
        self._hist.setdefault(key, []).append(seconds)

    def gauge(self, name: str, value: float, help_text: str = "",
              **labels: str) -> None:
        self._help.setdefault(name, help_text)
        self._counters[(name, tuple(sorted(labels.items())))] = value

    def render(self) -> str:
        lines: list[str] = []
        emitted: set[str] = set()

        def header(name: str, kind: str) -> None:
            if name in emitted:
                return
            emitted.add(name)
            if self._help.get(name):
                lines.append(f"# HELP {name} {self._help[name]}")
            lines.append(f"# TYPE {name} {kind}")

        for (name, labels), value in sorted(self._counters.items()):
            header(name, "counter")
            lines.append(f"{name}{_labels(labels)} {value:g}")

        for (name, labels), values in sorted(self._hist.items()):
            header(name, "histogram")
            total = len(values)
            for bucket in self.BUCKETS:
                below = sum(1 for v in values if v <= bucket)
                lines.append(
                    f"{name}_bucket{_labels(labels, le=str(bucket))} {below}")
            lines.append(f"{name}_bucket{_labels(labels, le='+Inf')} {total}")
            lines.append(f"{name}_sum{_labels(labels)} {sum(values):g}")
            lines.append(f"{name}_count{_labels(labels)} {total}")

        return "\n".join(lines) + "\n"


def _labels(pairs: tuple, **extra: str) -> str:
    items = list(pairs) + sorted(extra.items())
    if not items:
        return ""
    inner = ",".join(f'{k}="{_escape(str(v))}"' for k, v in items)
    return "{" + inner + "}"


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


metrics = _Metrics()
