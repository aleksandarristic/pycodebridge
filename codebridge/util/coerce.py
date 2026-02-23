"""Primitive coercion helpers used by config/runtime parsing."""

from __future__ import annotations

from typing import Any

_BOOL_TRUE = {"1", "true", "yes", "on"}
_BOOL_FALSE = {"0", "false", "no", "off"}


def parse_bool(value: Any) -> bool:
    """Parse bool/int/string values into a strict boolean."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        if value in (0, 1):
            return bool(value)
        raise ValueError(f"invalid boolean value: {value!r}")
    if isinstance(value, str):
        token = value.strip().lower()
        if token in _BOOL_TRUE:
            return True
        if token in _BOOL_FALSE:
            return False
    raise ValueError(f"invalid boolean value: {value!r}")
