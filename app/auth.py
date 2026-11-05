"""Single-user login, lockout and rate limiting. Fails closed when nothing is configured."""
from __future__ import annotations

import hmac
import threading
import time
from collections import defaultdict, deque

import bcrypt


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode()[:72], bcrypt.gensalt(rounds=12)).decode()


def verify_password(password: str, hashed: str) -> bool:
    if not hashed:
        return False  # no password configured means nobody gets in
    try:
        return bcrypt.checkpw(password.encode()[:72], hashed.encode())
    except ValueError:
        return False


class LoginGuard:
    """Lock an address out for a while after a few wrong passwords."""

    def __init__(self, max_failures: int = 5, lockout_s: int = 300, clock=time.monotonic):
        self.max_failures = max_failures
        self.lockout_s = lockout_s
        self._clock = clock
        self._fails: dict[str, int] = defaultdict(int)
        self._locked_until: dict[str, float] = {}
        self._lock = threading.Lock()

    def seconds_locked(self, key: str) -> int:
        with self._lock:
            until = self._locked_until.get(key, 0)
            left = until - self._clock()
            if left <= 0:
                self._locked_until.pop(key, None)
                return 0
            return int(left) + 1

    def failure(self, key: str) -> None:
        with self._lock:
            self._fails[key] += 1
            if self._fails[key] >= self.max_failures:
                self._locked_until[key] = self._clock() + self.lockout_s
                self._fails[key] = 0

    def success(self, key: str) -> None:
        with self._lock:
            self._fails.pop(key, None)
            self._locked_until.pop(key, None)


class RateLimiter:
    """Sliding window: at most `limit` hits per `window_s` per key."""

    def __init__(self, limit: int, window_s: int = 60, clock=time.monotonic):
        self.limit = limit
        self.window_s = window_s
        self._clock = clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = self._clock()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > self.window_s:
                q.popleft()
            if len(q) >= self.limit:
                return False
            q.append(now)
            return True


def same_secret(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())
