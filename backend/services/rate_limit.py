"""In-memory sliding-window rate limiting for the sign-in and sign-up endpoints.

Two guards:
  - per client IP, per endpoint: at most N requests a minute (stops floods and mass sign-ups);
  - per username: after N failed logins within the window, further attempts for that username are
    refused until the window passes, even with the right password (stops password guessing).

State is per process: with several uvicorn workers each keeps its own counts. Behind a reverse proxy
every request comes from the proxy's IP, so set the per-IP limit with that in mind.
"""
import math
import threading
import time
from collections import deque


class RateLimited(Exception):
    def __init__(self, retry_after: int) -> None:
        super().__init__(f"retry after {retry_after}s")
        self.retry_after = retry_after


class SlidingWindow:
    """Allows at most `limit` events per key within `window_s` seconds."""

    def __init__(self, limit: int, window_s: float, *, max_keys: int = 100_000) -> None:
        self.limit = limit
        self.window_s = window_s
        self._max_keys = max_keys
        self._events: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float) -> deque[float]:
        q = self._events.get(key)
        if q is None:
            if len(self._events) >= self._max_keys:
                self._evict(now)
            q = self._events[key] = deque()
        while q and q[0] <= now - self.window_s:
            q.popleft()
        return q

    def _evict(self, now: float) -> None:
        for k in [k for k, q in self._events.items() if not q or q[-1] <= now - self.window_s]:
            del self._events[k]
        while len(self._events) >= self._max_keys:
            self._events.pop(next(iter(self._events)))

    def check(self, key: str) -> None:
        """Raise RateLimited if `key` is at its limit (without recording anything)."""
        now = time.monotonic()
        with self._lock:
            q = self._prune(key, now)
            if len(q) >= self.limit:
                raise RateLimited(max(1, math.ceil(q[0] + self.window_s - now)))

    def hit(self, key: str) -> None:
        """Record one event for `key`, raising RateLimited if that goes over the limit."""
        now = time.monotonic()
        with self._lock:
            q = self._prune(key, now)
            if len(q) >= self.limit:
                raise RateLimited(max(1, math.ceil(q[0] + self.window_s - now)))
            q.append(now)

    def reset(self, key: str) -> None:
        with self._lock:
            self._events.pop(key, None)


class AuthRateLimiter:
    def __init__(self, *, ip_per_minute: int, max_failures: int, lockout_minutes: int) -> None:
        self.ip = SlidingWindow(ip_per_minute, 60)
        self.failures = SlidingWindow(max_failures, lockout_minutes * 60)
