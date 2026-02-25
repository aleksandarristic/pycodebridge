"""Unified per-session JSONL logging with archival rotation."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tarfile
import tempfile
import time
import contextlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

SAFE_SEG_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_DEFAULT_ACTIVE_RETENTION_DAYS = 30
_MAINTENANCE_INTERVAL_SECONDS = 300


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_segment(val: str, fallback: str) -> str:
    if not val:
        val = fallback
    if SAFE_SEG_RE.match(val):
        return val
    digest = hashlib.sha1(val.encode("utf-8")).hexdigest()[:12]
    return f"{fallback}-{digest}"


class SessionJsonlLogger:
    """Write all session events into one JSONL stream per channel/session."""

    def __init__(self, log_dir: str, active_retention_days: int = _DEFAULT_ACTIVE_RETENTION_DAYS) -> None:
        if not log_dir:
            raise ValueError("log dir is required")
        self._base = Path(log_dir) / "session_jsonl"
        self._active_dir = self._base / "active"
        self._archive_dir = self._base / "archive"
        self._retention_seconds = max(1, int(active_retention_days)) * 24 * 60 * 60
        self._next_maintenance_at = 0.0
        self._active_dir.mkdir(parents=True, exist_ok=True)
        self._archive_dir.mkdir(parents=True, exist_ok=True)
        self.cleanup()

    def append(self, channel_id: str, session: str, event: str, data: Optional[dict[str, Any]] = None) -> None:
        self._maybe_run_maintenance()
        channel_safe = _safe_segment(channel_id, "channel")
        session_safe = _safe_segment(session or "default", "default")
        path = self._active_dir / channel_safe / f"{session_safe}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "timestamp": _utc_now_iso(),
            "channel_id": channel_id,
            "session": session or "default",
            "event": event,
            "data": data or {},
        }
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=True) + "\n")

    def cleanup(self) -> None:
        cutoff = time.time() - self._retention_seconds
        for path in self._active_dir.rglob("*.jsonl"):
            if not path.is_file():
                continue
            try:
                mtime = path.stat().st_mtime
            except FileNotFoundError:
                continue
            if mtime >= cutoff:
                continue
            self._archive_then_remove(path, mtime)

    def _maybe_run_maintenance(self) -> None:
        now = time.time()
        if now < self._next_maintenance_at:
            return
        self.cleanup()
        self._next_maintenance_at = now + _MAINTENANCE_INTERVAL_SECONDS

    def _archive_then_remove(self, path: Path, mtime: float) -> None:
        rel = path.relative_to(self._active_dir)
        archive_parent = (self._archive_dir / rel.parent)
        archive_parent.mkdir(parents=True, exist_ok=True)
        stamp = datetime.fromtimestamp(mtime, tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        archive_name = f"{path.stem}-{stamp}.tgz"
        archive_path = archive_parent / archive_name
        fd, tmp_name = tempfile.mkstemp(prefix=f".{path.stem}-", suffix=".tgz", dir=str(archive_parent))
        os.close(fd)
        try:
            with tarfile.open(tmp_name, mode="w:gz") as tar:
                tar.add(str(path), arcname=path.name)
            os.replace(tmp_name, archive_path)
            path.unlink()
        finally:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(tmp_name)


class SessionJsonlHelper:
    """Safe wrapper around session JSONL logging."""

    def __init__(self, logger: Optional[SessionJsonlLogger], app_logger: Any) -> None:
        self._logger = logger
        self._app_logger = app_logger

    def append(self, channel_id: str, session: str, event: str, data: Optional[dict[str, Any]] = None) -> None:
        if not self._logger:
            return
        try:
            self._logger.append(channel_id, session, event, data)
        except Exception as exc:
            self._app_logger.warning("session_jsonl.append_failed", extra={"event": event, "error": str(exc)})
