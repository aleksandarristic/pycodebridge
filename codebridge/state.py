"""State persistence for channel/session mappings."""

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

from filelock import FileLock

CURRENT_VERSION = 1


@dataclass
class SessionState:
    """State for a single Codex session."""
    repo_name: str
    repo_path: str
    thread_id: str
    model: str = ""
    created_at: str = ""
    last_used_at: str = ""


@dataclass
class ChannelState:
    """State for a Discord channel, including sessions and sticky selections."""
    sessions: Dict[str, SessionState] = field(default_factory=dict)
    sticky: Dict[str, str] = field(default_factory=dict)


@dataclass
class FileState:
    """Top-level state container stored on disk."""
    version: int = CURRENT_VERSION
    channels: Dict[str, ChannelState] = field(default_factory=dict)
    dm_bindings: Dict[str, str] = field(default_factory=dict)


class Store:
    """State store with file locking and atomic writes."""
    def __init__(self, data_dir: str, lock_timeout_seconds: int = 600) -> None:
        if not data_dir:
            raise ValueError("data_dir is required")
        os.makedirs(data_dir, exist_ok=True)
        self.path = os.path.join(data_dir, "state.json")
        self.lock_path = self.path + ".lock"
        self.lock_timeout_seconds = max(lock_timeout_seconds, 1)
        self._lock = FileLock(self.lock_path, timeout=self.lock_timeout_seconds)

    def load(self) -> FileState:
        """Load state from disk or return an empty default."""
        with self._lock:
            return self._read_unlocked()

    def save(self, state: FileState) -> None:
        """Persist state to disk."""
        with self._lock:
            self._write_unlocked(state)

    def update(self, mutator: Callable[[FileState], None]) -> FileState:
        """Update state via a mutator callback under lock."""
        with self._lock:
            state = self._read_unlocked()
            mutator(state)
            self._write_unlocked(state)
            return state

    def _read_unlocked(self) -> FileState:
        """Read state without acquiring the file lock."""
        if not os.path.exists(self.path):
            return FileState(version=CURRENT_VERSION, channels={})
        with open(self.path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return _from_dict(data)

    def _write_unlocked(self, state: FileState) -> None:
        """Write state without acquiring the file lock."""
        if state.version == 0:
            state.version = CURRENT_VERSION
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_to_dict(state), f, indent=2)
        os.replace(tmp, self.path)


def _from_dict(data: Dict[str, Any]) -> FileState:
    """Deserialize a FileState from a raw dictionary."""
    version = int(data.get("version", CURRENT_VERSION))
    channels_raw = data.get("channels", {}) or {}
    dm_bindings = data.get("dm_bindings", {}) or {}
    channels: Dict[str, ChannelState] = {}

    for channel_id, ch in channels_raw.items():
        sessions_raw = (ch or {}).get("sessions", {}) or {}
        sticky = (ch or {}).get("sticky", {}) or {}
        sessions: Dict[str, SessionState] = {}
        for name, s in sessions_raw.items():
            sessions[name] = SessionState(
                repo_name=s.get("repo_name", ""),
                repo_path=s.get("repo_path", ""),
                thread_id=s.get("thread_id", ""),
                model=s.get("model", ""),
                created_at=s.get("created_at", ""),
                last_used_at=s.get("last_used_at", ""),
            )
        channels[channel_id] = ChannelState(sessions=sessions, sticky=dict(sticky))

    fs = FileState(version=version, channels=channels, dm_bindings=dict(dm_bindings))
    _migrate_legacy(fs, data)
    return fs


def _migrate_legacy(fs: FileState, raw: Dict[str, Any]) -> None:
    """Migrate legacy single-session schema into default session."""
    # If legacy fields exist, move them into default session.
    channels_raw = raw.get("channels", {}) or {}
    for channel_id, ch in channels_raw.items():
        if channel_id not in fs.channels:
            continue
        if fs.channels[channel_id].sessions:
            continue
        legacy_repo = ch.get("repo_name")
        legacy_thread = ch.get("thread_id")
        if not legacy_repo and not legacy_thread:
            continue
        fs.channels[channel_id].sessions["default"] = SessionState(
            repo_name=ch.get("repo_name", ""),
            repo_path=ch.get("repo_path", ""),
            thread_id=ch.get("thread_id", ""),
            created_at=ch.get("created_at", ""),
            last_used_at=ch.get("last_used_at", ""),
        )
        if not fs.channels[channel_id].sticky:
            fs.channels[channel_id].sticky = {}


def _to_dict(state: FileState) -> Dict[str, Any]:
    """Serialize FileState to a JSON-serializable dictionary."""
    channels: Dict[str, Any] = {}
    for channel_id, ch in state.channels.items():
        sessions: Dict[str, Any] = {}
        for name, s in ch.sessions.items():
            sessions[name] = {
                "repo_name": s.repo_name,
                "repo_path": s.repo_path,
                "thread_id": s.thread_id,
                "model": s.model,
                "created_at": s.created_at,
                "last_used_at": s.last_used_at,
            }
        channels[channel_id] = {
            "sessions": sessions,
            "sticky": ch.sticky,
        }
    return {"version": state.version, "channels": channels, "dm_bindings": state.dm_bindings}


def utc_now_iso() -> str:
    """Return current UTC time in ISO8601 format."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
