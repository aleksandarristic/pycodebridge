"""Audit logging for Codex/Discord interactions."""

import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from ..util.session_artifacts import (
    parse_session_artifact_label,
    parse_thread_artifact_label,
    safe_segment,
    session_artifact_label,
    thread_artifact_label,
)

_LOG = logging.getLogger(__name__)


@dataclass
class Entry:
    """Open audit log entry for a single request cycle."""
    seq: str
    channel_id: str
    session: str
    thread_id: str
    codex_path: str
    discord_path: str
    stderr_path: str

    _codex_file: Optional[Any] = None
    _discord_file: Optional[Any] = None
    _stderr_file: Optional[Any] = None
    _redact: Optional["Redactor"] = None

    def append_codex_line(self, line: str) -> None:
        """Append a raw JSONL line from Codex output."""
        if self._codex_file:
            if self._redact:
                line = self._redact.apply_text(line)
            self._codex_file.write(line + "\n")
            self._codex_file.flush()

    def append_discord_out(self, text: str) -> None:
        """Append text sent to Discord for this request."""
        if self._discord_file:
            if self._redact:
                text = self._redact.apply_text(text)
            self._discord_file.write(text + "\n")
            self._discord_file.flush()

    def append_stderr(self, text: str) -> None:
        """Append stderr text from Codex process."""
        if self._stderr_file:
            if self._redact:
                text = self._redact.apply_text(text)
            self._stderr_file.write(text + "\n")
            self._stderr_file.flush()

    def close(self) -> None:
        """Close any open file handles for this entry."""
        for f in (self._codex_file, self._discord_file, self._stderr_file):
            if f:
                try:
                    f.flush()
                    f.close()
                except Exception as exc:
                    _LOG.warning("audit.entry.close_failed path=%s error=%s", getattr(f, "name", "unknown"), exc)


@dataclass
class Summary:
    """Summary metadata for an audit entry."""
    seq: str
    channel_id: str
    session: str
    thread_id: str
    request: Dict[str, Any]
    path: str
    started_at: str
    ended_at: str
    repo_name: str = ""


class Logger:
    """Audit logger managing per-channel/session/thread directories."""
    def __init__(self, base_dir: str, redactor: Optional["Redactor"] = None) -> None:
        if not base_dir:
            raise ValueError("log dir is required")
        os.makedirs(base_dir, exist_ok=True)
        self.base_dir = base_dir
        self._redactor = redactor

    def start(self, channel_id: str, session: str, thread_id: str, request: Any) -> Entry:
        """Start a new audit entry and return its writer."""
        session = session or "default"
        channel_safe = safe_segment(channel_id, "channel")
        request_map = request if isinstance(request, dict) else {}
        repo_name = str((request_map or {}).get("repo_name") or "")
        session_dir = session_artifact_label(repo_name, session)
        thread_safe = thread_artifact_label(thread_id)

        entry_dir = os.path.join(self.base_dir, channel_safe, session_dir, thread_safe)
        os.makedirs(entry_dir, exist_ok=True)

        seq = _next_seq(entry_dir)
        request_path = os.path.join(entry_dir, f"{seq}.request.json")
        if self._redactor:
            request = self._redactor.apply_obj(request)
        _write_json(request_path, request)

        codex_path = os.path.join(entry_dir, f"{seq}.codex.jsonl")
        discord_path = os.path.join(entry_dir, f"{seq}.discord_out.txt")
        stderr_path = os.path.join(entry_dir, f"{seq}.codex.stderr.txt")

        entry = Entry(
            seq=seq,
            channel_id=channel_id,
            session=session,
            thread_id=thread_id,
            codex_path=codex_path,
            discord_path=discord_path,
            stderr_path=stderr_path,
        )
        entry._redact = self._redactor
        entry._codex_file = open(codex_path, "w", encoding="utf-8")
        entry._discord_file = open(discord_path, "w", encoding="utf-8")
        entry._stderr_file = open(stderr_path, "w", encoding="utf-8")
        return entry

    def summaries(self, channel_id: str, session: str, limit: int) -> list[Summary]:
        """Return recent audit summaries for a channel/session."""
        summaries: list[Summary] = []
        if channel_id:
            channel_id = safe_segment(channel_id, "channel")
        if session:
            session = safe_segment(session, "default")

        channels = [channel_id] if channel_id else [d for d in os.listdir(self.base_dir) if os.path.isdir(os.path.join(self.base_dir, d))]
        for ch in channels:
            channel_dir = os.path.join(self.base_dir, ch)
            if not os.path.isdir(channel_dir):
                continue
            session_dirs = [d for d in os.listdir(channel_dir) if os.path.isdir(os.path.join(channel_dir, d))]
            for sess_dir_name in session_dirs:
                parsed_repo, parsed_session = parse_session_artifact_label(sess_dir_name)
                resolved_session = parsed_session or "default"
                if session and resolved_session != session:
                    continue
                sess_dir = os.path.join(channel_dir, sess_dir_name)
                if not os.path.isdir(sess_dir):
                    continue
                for thread_dir_name in os.listdir(sess_dir):
                    thread_dir = os.path.join(sess_dir, thread_dir_name)
                    if not os.path.isdir(thread_dir):
                        continue
                    for fname in os.listdir(thread_dir):
                        if not fname.endswith(".request.json"):
                            continue
                        path = os.path.join(thread_dir, fname)
                        try:
                            with open(path, "r", encoding="utf-8") as f:
                                req = json.load(f)
                            seq = fname.split(".")[0]
                            request_ts = str(req.get("timestamp") or "").strip()
                            started_at = request_ts if request_ts else _mtime_iso(path)
                            ended_at = _entry_end_iso(thread_dir, seq, started_at)
                            req_repo = str(req.get("repo_name") or "").strip()
                            repo_name = req_repo or parsed_repo
                            summaries.append(
                                Summary(
                                    seq=seq,
                                    channel_id=ch,
                                    session=resolved_session,
                                    thread_id=parse_thread_artifact_label(thread_dir_name),
                                    request=req,
                                    path=thread_dir,
                                    started_at=started_at,
                                    ended_at=ended_at,
                                    repo_name=repo_name,
                                )
                            )
                        except Exception as exc:
                            _LOG.warning("audit.summaries.read_failed path=%s error=%s", path, exc)
                            continue

        summaries.sort(key=lambda s: s.seq, reverse=True)
        if limit > 0:
            summaries = summaries[:limit]
        return summaries


class Redactor:
    """Redact secrets from text and JSON-like payloads."""

    def __init__(self, patterns: Optional[list[str]] = None) -> None:
        if patterns is None or len(patterns) == 0:
            patterns = _default_redaction_patterns()
        self._regexes = [re.compile(p) for p in patterns]

    def apply_text(self, text: str) -> str:
        """Redact secrets in a plain string."""
        if not text:
            return text
        for rx in self._regexes:
            text = rx.sub("<redacted>", text)
        return text

    def apply_obj(self, obj: Any) -> Any:
        """Redact secrets in a JSON-like object."""
        if isinstance(obj, dict):
            return {k: self.apply_obj(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self.apply_obj(v) for v in obj]
        if isinstance(obj, str):
            return self.apply_text(obj)
        return obj



def _next_seq(entry_dir: str) -> str:
    """Allocate the next sequence number for an entry directory."""
    latest_path = os.path.join(entry_dir, ".latest")
    next_val = 1
    if os.path.exists(latest_path):
        try:
            with open(latest_path, "r", encoding="utf-8") as f:
                val = int(f.read().strip() or 0)
                next_val = val + 1
        except Exception as exc:
            _LOG.warning("audit.next_seq_latest_read_failed path=%s error=%s", latest_path, exc)
    if next_val == 1:
        for fname in os.listdir(entry_dir):
            if fname.endswith(".request.json"):
                try:
                    val = int(fname.split(".")[0])
                    next_val = max(next_val, val + 1)
                except Exception:
                    continue
    with open(latest_path, "w", encoding="utf-8") as f:
        f.write(str(next_val))
    return f"{next_val:06d}"


def _write_json(path: str, payload: Any) -> None:
    """Write JSON to disk with indentation."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def _default_redaction_patterns() -> list[str]:
    return [
        r"sk-[A-Za-z0-9]{20,}",
        r"ghp_[A-Za-z0-9]{20,}",
        r"xox[bap]-[A-Za-z0-9-]{10,}",
        r"xapp-[A-Za-z0-9-]{10,}",
        r"(?i)(token|secret|password)\s*[:=]\s*[^\s]+",
    ]


def _mtime_iso(path: str) -> str:
    try:
        return datetime.fromtimestamp(os.path.getmtime(path), tz=timezone.utc).isoformat()
    except Exception:
        return ""


def _entry_end_iso(thread_dir: str, seq: str, fallback: str) -> str:
    candidates = [
        os.path.join(thread_dir, f"{seq}.codex.jsonl"),
        os.path.join(thread_dir, f"{seq}.discord_out.txt"),
        os.path.join(thread_dir, f"{seq}.codex.stderr.txt"),
        os.path.join(thread_dir, f"{seq}.request.json"),
    ]
    mtimes: list[float] = []
    for p in candidates:
        try:
            mtimes.append(os.path.getmtime(p))
        except Exception:
            continue
    if not mtimes:
        return fallback
    return datetime.fromtimestamp(max(mtimes), tz=timezone.utc).isoformat()
