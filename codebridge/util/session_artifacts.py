"""Helpers for session artifact naming and path-safe labels."""

from __future__ import annotations

import hashlib
import re
from typing import Optional, Tuple

SAFE_SEG_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_SESSION_LABEL_RE = re.compile(r"^repo-(?P<repo>.+)__session-(?P<session>.+)$")


def safe_segment(value: str, fallback: str) -> str:
    """Return a path-safe segment, hashing values that do not match policy."""
    raw = (value or "").strip()
    if not raw:
        raw = fallback
    if SAFE_SEG_RE.match(raw):
        return raw
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
    return f"{fallback}-{digest}"


def session_artifact_label(repo_name: str, session: str) -> str:
    """Build a human-readable session label containing repo + session prefixes."""
    repo = safe_segment(repo_name, "unknown")
    sess = safe_segment(session or "default", "default")
    return f"repo-{repo}__session-{sess}"


def parse_session_artifact_label(name: str) -> Tuple[str, str]:
    """Parse prefixed session label; fall back to legacy session-only names."""
    token = (name or "").strip()
    m = _SESSION_LABEL_RE.match(token)
    if m:
        return m.group("repo"), m.group("session")
    return "", token


def thread_artifact_label(thread_id: str) -> str:
    """Build a path-safe, prefixed thread folder label."""
    return f"thread-{safe_segment(thread_id, 'pending')}"


def parse_thread_artifact_label(name: str) -> str:
    """Parse thread folder label; support prefixed and legacy values."""
    token = (name or "").strip()
    if token.startswith("thread-"):
        return token[len("thread-") :]
    return token

