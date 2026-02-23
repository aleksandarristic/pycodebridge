"""TOTP verification helpers backed by pyotp."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from collections import deque
import time
from typing import Callable, Deque, Dict

import pyotp


@dataclass
class _LimiterState:
    failures: Deque[float] = field(default_factory=deque)
    locked_until: float = 0.0


class TotpAttemptLimiter:
    """Simple in-memory lockout limiter for repeated TOTP failures."""

    def __init__(
        self,
        *,
        max_failures: int,
        window_seconds: int,
        cooldown_seconds: int,
        now_fn: Callable[[], float] | None = None,
    ) -> None:
        self.max_failures = max(0, int(max_failures))
        self.window_seconds = max(1, int(window_seconds))
        self.cooldown_seconds = max(0, int(cooldown_seconds))
        self._now = now_fn or time.time
        self._states: Dict[str, _LimiterState] = {}

    def check_allowed(self, key: str) -> tuple[bool, int]:
        """Return (allowed, retry_after_seconds)."""
        if self.max_failures == 0 or self.cooldown_seconds == 0:
            return True, 0
        now = self._now()
        state = self._states.get(key)
        if state is None:
            return True, 0
        self._prune_failures(state, now)
        if state.locked_until > now:
            retry = int(math.ceil(state.locked_until - now))
            return False, max(1, retry)
        if not state.failures:
            self._states.pop(key, None)
        return True, 0

    def record_failure(self, key: str) -> int:
        """Record a failure and return lockout seconds if lock was entered."""
        if self.max_failures == 0 or self.cooldown_seconds == 0:
            return 0
        now = self._now()
        state = self._states.setdefault(key, _LimiterState())
        self._prune_failures(state, now)
        state.failures.append(now)
        if len(state.failures) < self.max_failures:
            return 0
        state.locked_until = now + self.cooldown_seconds
        state.failures.clear()
        return self.cooldown_seconds

    def record_success(self, key: str) -> None:
        """Clear failure history after successful verification."""
        self._states.pop(key, None)

    def _prune_failures(self, state: _LimiterState, now: float) -> None:
        threshold = now - float(self.window_seconds)
        while state.failures and state.failures[0] < threshold:
            state.failures.popleft()


def verify_totp(
    code: str,
    secret_b32: str,
    *,
    period: int = 30,
    window: int = 1,
    now: int | None = None,
) -> int | None:
    """Return matched TOTP step on success, else None."""
    token = (code or "").strip()
    if len(token) != 6 or not token.isdigit():
        return None
    try:
        totp = pyotp.TOTP("".join(secret_b32.strip().split()).upper(), interval=period)
    except Exception:
        return None
    current = int((now if now is not None else time.time()) // period)
    for delta in range(-window, window + 1):
        step = current + delta
        if step < 0:
            continue
        ts = step * period
        if totp.verify(token, for_time=ts, valid_window=0):
            return step
    return None
