"""TOTP verification helpers backed by pyotp."""

from __future__ import annotations

import time

import pyotp


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
