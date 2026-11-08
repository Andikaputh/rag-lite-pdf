"""Per-session sliding-window request limits.

State lives in one process only: it resets on restart and is never shared
across workers. That matches the single-worker deployment documented in
docs/DEPLOYMENT.md; multi-worker sessions remain an open release gate.
"""
import math
import threading
import time
from collections import deque

# Generous human-facing budget for the chat composer. The evaluation harness
# (evals/run.py) disables it explicitly when constructing its own app instance;
# there is no HTTP path that can disable or reconfigure the limit.
CHAT_RATE_LIMIT = 30
CHAT_RATE_WINDOW_SECONDS = 60.0


class SlidingWindowLimiter:
    """Allow at most ``max_requests`` hits per key inside a sliding window."""

    def __init__(self, max_requests: int, window_seconds: float, *, now=time.monotonic):
        if max_requests < 1 or window_seconds <= 0:
            raise ValueError("limit must allow at least one hit per positive window")
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._now = now
        self._lock = threading.Lock()
        self._hits: dict[str, deque[float]] = {}

    def check(self, key: str) -> tuple[bool, float]:
        """Consume one hit for ``key``.

        Returns ``(allowed, retry_after_seconds)``. Denied attempts are not
        recorded, so a client cannot extend its own lockout by retrying.
        Expired buckets are pruned opportunistically so memory stays bounded
        by active sessions instead of every session ever seen.
        """
        now = self._now()
        cutoff = now - self.window_seconds
        with self._lock:
            for token in list(self._hits):
                bucket = self._hits[token]
                while bucket and bucket[0] <= cutoff:
                    bucket.popleft()
                if not bucket:
                    del self._hits[token]
            bucket = self._hits.get(key)
            if bucket is None:
                bucket = self._hits[key] = deque()
            if len(bucket) >= self.max_requests:
                return False, max(0.0, bucket[0] + self.window_seconds - now)
            bucket.append(now)
            return True, 0.0

    @staticmethod
    def retry_after_header(retry_after: float) -> str:
        """Whole seconds, at least 1, as required for Retry-After."""
        return str(max(1, math.ceil(retry_after)))
