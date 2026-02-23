"""Helpers to centralize audit lifecycle behavior."""

from __future__ import annotations

from typing import Any, Optional

from .audit import Entry, Logger as AuditLogger


class AuditHelper:
    """Wrap audit logging with safe error handling."""

    def __init__(self, audit: Optional[AuditLogger], logger) -> None:
        self._audit = audit
        self._logger = logger

    def start(self, channel_id: str, session: str, thread_id: str, meta: Any) -> Optional[Entry]:
        if not self._audit:
            return None
        try:
            return self._audit.start(channel_id, session, thread_id, meta)
        except Exception as exc:
            self._logger.error("audit.start_failed", extra={"channel_id": channel_id, "session": session, "error": str(exc)})
            return None

    def append_codex(self, entry: Optional[Entry], line: str) -> None:
        if entry:
            try:
                entry.append_codex_line(line)
            except Exception as exc:
                self._logger.warning("audit.append_codex_failed", extra={"error": str(exc)})

    def append_output(self, entry: Optional[Entry], msg: str) -> None:
        if entry:
            try:
                entry.append_discord_out(msg)
            except Exception as exc:
                self._logger.warning("audit.append_output_failed", extra={"error": str(exc)})

    def append_stderr(self, entry: Optional[Entry], msg: str) -> None:
        if entry:
            try:
                entry.append_stderr(msg)
            except Exception as exc:
                self._logger.warning("audit.append_stderr_failed", extra={"error": str(exc)})

    def close(self, entry: Optional[Entry]) -> None:
        if entry:
            try:
                entry.close()
            except Exception as exc:
                self._logger.warning("audit.close_failed", extra={"error": str(exc)})
