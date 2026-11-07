"""Logging setup: secret redaction filter + rotating file handler.

Called once from cli/main.py before uvicorn starts. Two concerns:

1. Redaction: a `logging.Filter` that scrubs common secret shapes (sk-...
   style API keys, `Bearer <token>` headers, and generic 20+ char opaque
   tokens) out of every log record's message and args before it's
   formatted/written, so an accidental `logger.info(str(headers))` or an
   exception traceback that includes a key never lands in the log file.
2. Rotating file handler writing to `<data_root>/logs/application.log`, so
   logs persist across restarts without growing unboundedly.
"""

from __future__ import annotations

import logging
import logging.handlers
import re

from local_ai_workspace.storage.paths import logs_dir

# Patterns matched and replaced with "[REDACTED]" wherever they appear in a
# log message. Order matters only in that more specific patterns run first;
# since we use re.sub with |, overlapping redaction is fine either way.
_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{10,}"),  # OpenAI/Anthropic-style API keys
    re.compile(r"Bearer\s+[A-Za-z0-9._-]{10,}", re.IGNORECASE),  # Authorization headers
    re.compile(r"\b[A-Za-z0-9_-]{20,}\b"),  # any generic 20+ char opaque token
]

_REDACTED = "[REDACTED]"


def redact(text: str) -> str:
    """Replace any substring matching a known secret pattern with [REDACTED]."""
    if not text:
        return text
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(_REDACTED, text)
    return text


class RedactionFilter(logging.Filter):
    """Logging filter that redacts secret-shaped substrings from both the
    raw message and any string arguments before the record is formatted."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            if isinstance(record.msg, str):
                record.msg = redact(record.msg)
            if record.args:
                if isinstance(record.args, dict):
                    record.args = {k: redact(v) if isinstance(v, str) else v for k, v in record.args.items()}
                else:
                    record.args = tuple(redact(a) if isinstance(a, str) else a for a in record.args)
        except Exception:  # noqa: BLE001 - redaction must never break logging
            pass
        return True


def configure_logging(level: str = "INFO") -> None:
    """Configure the root logger with: the redaction filter (applied before
    any handler formats a record), a rotating file handler writing to
    <data_root>/logs/application.log, and a console handler."""
    root = logging.getLogger()
    root.setLevel(level.upper())

    redaction_filter = RedactionFilter()

    log_path = logs_dir() / "application.log"
    file_handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    file_handler.addFilter(redaction_filter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    console_handler.addFilter(redaction_filter)

    # Replace any pre-existing handlers to avoid duplicate log lines if this
    # is called more than once (e.g. in tests).
    root.handlers.clear()
    root.addHandler(file_handler)
    root.addHandler(console_handler)
