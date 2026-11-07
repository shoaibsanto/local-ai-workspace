"""Small atomic JSON read/write helpers used across the storage layer.

All writes are atomic (write to temp file + os.replace) so a crash mid-write
never corrupts existing data — important since there's no database to fall
back on.

Atomicity of a *single* write is not the same thing as safety under
*concurrent* read-modify-write sequences, though: two callers (e.g. two
in-flight requests appending to the same conversation's messages.jsonl, or
two settings updates) can each read the same "before" state, compute their
own update, and then write — the second write wins and the first's change
is silently lost, even though each individual write was atomic.

`get_lock()` below hands out a per-resource lock (keyed by conversation id,
or by an absolute settings-file path) for callers (storage/
conversation_store.py, storage/settings_store.py) to hold for the *whole*
read-modify-write sequence.

Deliberately a `threading.Lock`, not an `asyncio.Lock`: FastAPI/Starlette
runs plain `def` (non-async) endpoint handlers in a worker threadpool, not
on the event loop thread, so two concurrent requests to a sync endpoint
(e.g. two PATCH /api/conversations/{id} calls) genuinely race across OS
threads, not just across asyncio tasks on one thread -- an asyncio.Lock is
bound to one event loop/thread and would not serialize that case at all.
A `threading.Lock` correctly serializes both: concurrent worker threads
running sync handlers, and concurrent coroutines on the event loop thread
(acquiring an uncontended threading.Lock is cheap enough here given these
are small local JSON/JSONL files, not network calls).
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# One threading.Lock per resource key (e.g. a conversation id or an
# absolute settings file path), created lazily and kept for the life of the
# process. Creation of a new Lock-for-a-key is itself guarded by
# `_locks_guard` so two threads racing to create the *first* lock for the
# same previously-unseen key can't end up with two different Lock objects
# (a plain `defaultdict` is not safe for that under real OS-thread
# concurrency, unlike under single-threaded asyncio).
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def get_lock(key: str) -> threading.Lock:
    """Return the process-wide lock for `key`, creating it on first use.
    Callers must hold this for the *entire* read-modify-write sequence
    against the resource `key` identifies, not just around the final
    write -- locking only the write still allows two readers to both read
    stale state before either writes."""
    lock = _locks.get(key)
    if lock is None:
        with _locks_guard:
            lock = _locks.setdefault(key, threading.Lock())
    return lock


def read_json(path: Path, default: Any = None) -> Any:
    """Read a JSON file, returning `default` (None unless overridden) if the
    file is missing, unreadable, or corrupted (invalid JSON) rather than
    raising — a single corrupted file should never crash the whole app."""
    if not path.exists():
        return default
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        logger.warning("Corrupted JSON file, treating as missing: %s", path)
        return default
    except OSError:
        return default


def write_json_atomic(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> list[dict]:
    """Read a JSONL file, skipping (and warning about) any malformed lines
    instead of aborting the whole read."""
    if not path.exists():
        return []
    records = []
    with open(path, encoding="utf-8") as f:
        for lineno, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                logger.warning("Skipping malformed JSONL line %d in %s", lineno, path)
                continue
    return records


def rewrite_jsonl_atomic(path: Path, records: list[dict]) -> None:
    """Rewrite an entire JSONL file atomically (used for edit/delete-in-place)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=".jsonl")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise
