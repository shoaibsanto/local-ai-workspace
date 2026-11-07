"""In-memory sliding-window rate limiter for the chat/completion endpoints.

Scope is deliberately narrow: this app has 44+ routes, but the one real
cost/safety risk is a buggy frontend retry loop (or a runaway agent
self-triggering turns) hammering a *paid* LLM provider's API over and over,
burning the user's money on every call. Every other route here is free
(local filesystem CRUD) -- rate-limiting them would just be noise. So this
limiter is applied only to POST /api/conversations/{id}/chat and
.../tool_calls/{id}/resume, keyed per-conversation (not globally, and not
per-IP -- this is a single-user local app, there's no "other tenant" to
isolate from; the thing we're protecting against is one conversation's loop
going wild, not cross-conversation fairness).

Sliding window over a plain list of monotonic timestamps per conversation
id: cheap, no external dependency, correct enough for a local safety net
(not trying to be exact under adversarial clock manipulation).
"""

from __future__ import annotations

import threading
import time
from collections import deque


class ChatRateLimiter:
    """Per-key (conversation id) sliding-window rate limiter.

    `allow(key)` returns True and records the call if the key has made
    fewer than `limit_per_minute` calls in the trailing 60 seconds,
    otherwise returns False without recording anything (so a caller who's
    over the limit doesn't get to "use up" window space just by trying).
    """

    def __init__(self, window_seconds: float = 60.0):
        self._window_seconds = window_seconds
        self._calls: dict[str, deque[float]] = {}
        self._guard = threading.Lock()

    def allow(self, key: str, limit_per_minute: int) -> bool:
        if limit_per_minute <= 0:
            return True  # 0/negative = rate limiting disabled
        now = time.monotonic()
        cutoff = now - self._window_seconds
        with self._guard:
            calls = self._calls.setdefault(key, deque())
            while calls and calls[0] < cutoff:
                calls.popleft()
            if len(calls) >= limit_per_minute:
                return False
            calls.append(now)
            return True

    def reset(self) -> None:
        """Test helper: clear all recorded call history."""
        with self._guard:
            self._calls.clear()


# Process-wide singleton -- the app has exactly one of these, shared by the
# chat and resume endpoints (both draw from the same per-conversation
# budget since both ultimately call the paid provider).
chat_rate_limiter = ChatRateLimiter()
