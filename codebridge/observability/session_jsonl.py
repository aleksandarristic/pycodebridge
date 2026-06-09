"""Unified per-session JSONL logging with archival rotation."""

from __future__ import annotations

import json
import os
import tarfile
import tempfile
import time
import contextlib
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from ..util.session_artifacts import safe_segment, session_artifact_label

_DEFAULT_ACTIVE_RETENTION_DAYS = 30
_MAINTENANCE_INTERVAL_SECONDS = 300
_DEFAULT_FLUSH_INTERVAL_SECONDS = 1.0
_DEFAULT_MAX_BUFFERED_EVENTS = 32
_DEFAULT_MAX_BUFFERED_BYTES = 64 * 1024
_FORCE_FLUSH_EVENTS = frozenset(
    {
        "run.start",
        "run.start_failed",
        "run.complete",
        "run.failed",
        "run.terminal",
        "codex.exit",
        "codex.error",
        "codex.thread",
    }
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SessionJsonlLogger:
    """Write all session events into one JSONL stream per channel/session.

    Hot streaming events are buffered briefly and flushed in batches. Terminal
    and error events are flushed synchronously so the on-disk log remains
    durable at run boundaries.
    """

    def __init__(
        self,
        log_dir: str,
        active_retention_days: int = _DEFAULT_ACTIVE_RETENTION_DAYS,
        flush_interval_seconds: float = _DEFAULT_FLUSH_INTERVAL_SECONDS,
        max_buffered_events: int = _DEFAULT_MAX_BUFFERED_EVENTS,
        max_buffered_bytes: int = _DEFAULT_MAX_BUFFERED_BYTES,
        redactor: Optional[Any] = None,
    ) -> None:
        if not log_dir:
            raise ValueError("log dir is required")
        self._base = Path(log_dir) / "session_jsonl"
        self._active_dir = self._base / "active"
        self._archive_dir = self._base / "archive"
        self._retention_seconds = max(1, int(active_retention_days)) * 24 * 60 * 60
        self._flush_interval_seconds = max(0.0, float(flush_interval_seconds))
        self._max_buffered_events = max(1, int(max_buffered_events))
        self._max_buffered_bytes = max(1, int(max_buffered_bytes))
        self._redactor = redactor
        self._next_maintenance_at = 0.0
        self._next_flush_at = 0.0
        self._pending_lines: dict[Path, list[str]] = {}
        self._pending_bytes: dict[Path, int] = {}
        self._lock = threading.RLock()
        self._active_dir.mkdir(parents=True, exist_ok=True)
        self._archive_dir.mkdir(parents=True, exist_ok=True)
        self.cleanup()

    def append(
        self,
        channel_id: str,
        session: str,
        event: str,
        data: Optional[dict[str, Any]] = None,
        repo_name: str = "",
    ) -> None:
        with self._lock:
            self._maybe_run_maintenance()
            path = self._session_path(channel_id, session, repo_name)
            payload = {
                "timestamp": _utc_now_iso(),
                "channel_id": channel_id,
                "session": session or "default",
                "repo_name": repo_name or "",
                "event": event,
                "data": data or {},
            }
            if self._redactor:
                payload = self._redactor.apply_obj(payload)
            line = json.dumps(payload, ensure_ascii=True) + "\n"
            self._pending_lines.setdefault(path, []).append(line)
            self._pending_bytes[path] = self._pending_bytes.get(path, 0) + len(line.encode("utf-8"))
            if not self._next_flush_at and self._flush_interval_seconds > 0:
                self._next_flush_at = time.time() + self._flush_interval_seconds

            if event in _FORCE_FLUSH_EVENTS or self._flush_needed_for_path(path):
                self._flush_path(path)
            else:
                self._flush_due_paths()

    def cleanup(self) -> None:
        with self._lock:
            self._flush_all()
            self._cleanup_active_files()

    def _cleanup_active_files(self) -> None:
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
        self._flush_all()
        self._cleanup_active_files()
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

    def session_paths(self, channel_id: str, session: str, repo_name: str = "") -> list[Path]:
        """Return candidate active/archive paths for one logical session."""
        with self._lock:
            for path in self._candidate_active_paths(channel_id, session, repo_name):
                self._flush_path(path)
        channel_safe = safe_segment(channel_id, "channel")
        candidates = [session_artifact_label(repo_name, session or "default")]
        # Backward compatibility with pre-prefix naming.
        legacy = safe_segment(session or "default", "default")
        if legacy not in candidates:
            candidates.append(legacy)

        active: list[Path] = [self._active_dir / channel_safe / f"{label}.jsonl" for label in candidates]
        if not repo_name:
            wildcard_pattern = f"repo-*__session-{legacy}.jsonl"
            active.extend((self._active_dir / channel_safe).glob(wildcard_pattern))
        archive: list[Path] = []
        archive_dir = self._archive_dir / channel_safe
        if archive_dir.is_dir():
            for item in archive_dir.glob("*.tgz"):
                if any(item.name.startswith(f"{label}-") for label in candidates):
                    archive.append(item)
                elif not repo_name and f"__session-{legacy}-" in item.name:
                    archive.append(item)
        return active + archive

    def _session_path(self, channel_id: str, session: str, repo_name: str) -> Path:
        channel_safe = safe_segment(channel_id, "channel")
        session_label = session_artifact_label(repo_name, session or "default")
        return self._active_dir / channel_safe / f"{session_label}.jsonl"

    def _candidate_active_paths(self, channel_id: str, session: str, repo_name: str) -> list[Path]:
        channel_safe = safe_segment(channel_id, "channel")
        candidates = [session_artifact_label(repo_name, session or "default")]
        legacy = safe_segment(session or "default", "default")
        if legacy not in candidates:
            candidates.append(legacy)
        paths = [self._active_dir / channel_safe / f"{label}.jsonl" for label in candidates]
        if not repo_name:
            wildcard_pattern = f"repo-*__session-{legacy}.jsonl"
            paths.extend((self._active_dir / channel_safe).glob(wildcard_pattern))
        return list(paths)

    def _flush_needed_for_path(self, path: Path) -> bool:
        lines = self._pending_lines.get(path, [])
        return len(lines) >= self._max_buffered_events or self._pending_bytes.get(path, 0) >= self._max_buffered_bytes

    def _flush_due_paths(self) -> None:
        if not self._pending_lines or self._flush_interval_seconds <= 0:
            return
        now = time.time()
        if self._next_flush_at and now < self._next_flush_at:
            return
        self._flush_all()

    def _flush_all(self) -> None:
        for path in list(self._pending_lines.keys()):
            self._flush_path(path)
        self._next_flush_at = 0.0

    def _flush_path(self, path: Path) -> None:
        lines = self._pending_lines.get(path)
        if not lines:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        self._append_lines(path, lines)
        self._pending_lines.pop(path, None)
        self._pending_bytes.pop(path, None)
        if self._pending_lines:
            self._next_flush_at = time.time() + self._flush_interval_seconds if self._flush_interval_seconds > 0 else 0.0
        else:
            self._next_flush_at = 0.0

    def _append_lines(self, path: Path, lines: list[str]) -> None:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("".join(lines))


class SessionJsonlHelper:
    """Safe wrapper around session JSONL logging."""

    def __init__(self, logger: Optional[SessionJsonlLogger], app_logger: Any) -> None:
        self._logger = logger
        self._app_logger = app_logger

    def append(
        self,
        channel_id: str,
        session: str,
        event: str,
        data: Optional[dict[str, Any]] = None,
        repo_name: str = "",
    ) -> None:
        if not self._logger:
            return
        try:
            self._logger.append(channel_id, session, event, data, repo_name=repo_name)
        except Exception as exc:
            self._app_logger.warning("session_jsonl.append_failed", extra={"event": event, "error": str(exc)})

    def session_paths(self, channel_id: str, session: str, repo_name: str = "") -> list[Path]:
        if not self._logger:
            return []
        try:
            return self._logger.session_paths(channel_id, session, repo_name=repo_name)
        except Exception:
            return []
