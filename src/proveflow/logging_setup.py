"""Structured logging: stdlib logging with a JSON formatter, always to stderr.

Library code logs through ``logging.getLogger(__name__)``; user-facing CLI
output goes through Rich in ``cli.py``. Raw secret values must never be
passed to a logger — redaction happens at read time (see core.redact).
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any


class JsonFormatter(logging.Formatter):
    """Format each record as one JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


class _CurrentStderrHandler(logging.StreamHandler):  # type: ignore[type-arg]
    """Always writes to the *current* ``sys.stderr`` (survives stream swaps in tests)."""

    def emit(self, record: logging.LogRecord) -> None:
        self.stream = sys.stderr
        super().emit(record)


def configure(level: str = "WARNING") -> None:
    """Configure the root ``proveflow`` logger to emit JSON lines on stderr."""
    logger = logging.getLogger("proveflow")
    logger.setLevel(level.upper())
    if not logger.handlers:
        handler = _CurrentStderrHandler(sys.stderr)
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
    logger.propagate = False
