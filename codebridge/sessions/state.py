"""State persistence for channel/session mappings."""

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict

from filelock import FileLock
from ..util import path as pathutil

CURRENT_VERSION = 1
_BOOL_TRUE = {"1", "true", "yes", "on"}
_BOOL_FALSE = {"0", "false", "no", "off"}


@dataclass
class SessionState:
    """State for a single Codex session."""
    repo_name: str
    repo_path: str
    thread_id: str
    model: str = ""
    reasoning_effort: str = ""
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
    runtime_options_global: Dict[str, Any] = field(default_factory=dict)
    runtime_options_channels: Dict[str, Dict[str, Any]] = field(default_factory=dict)


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
    dm_bindings_raw = data.get("dm_bindings", {}) or {}
    runtime_global_raw = data.get("runtime_options_global", {}) or {}
    runtime_channels_raw = data.get("runtime_options_channels", {}) or {}
    channels: Dict[str, ChannelState] = {}
    dm_bindings: Dict[str, str] = {}
    runtime_options_global: Dict[str, Any] = {}
    runtime_options_channels: Dict[str, Dict[str, Any]] = {}
    for key, value in dm_bindings_raw.items():
        repo = _normalize_repo_name(value)
        if repo:
            dm_bindings[str(key)] = repo
    for key, value in runtime_global_raw.items():
        normalized = _normalize_runtime_option_value(str(key), value)
        if normalized is not None:
            runtime_options_global[str(key)] = normalized
    for channel_id, values in runtime_channels_raw.items():
        raw_values = values if isinstance(values, dict) else {}
        scoped: Dict[str, Any] = {}
        for key, value in raw_values.items():
            normalized = _normalize_runtime_option_value(str(key), value)
            if normalized is not None:
                scoped[str(key)] = normalized
        if scoped:
            runtime_options_channels[str(channel_id)] = scoped

    for channel_id, ch in channels_raw.items():
        sessions_raw = (ch or {}).get("sessions", {}) or {}
        sticky = (ch or {}).get("sticky", {}) or {}
        sessions: Dict[str, SessionState] = {}
        for name, s in sessions_raw.items():
            sessions[name] = SessionState(
                repo_name=_normalize_repo_name(s.get("repo_name", "")),
                repo_path=s.get("repo_path", ""),
                thread_id=s.get("thread_id", ""),
                model=s.get("model", ""),
                reasoning_effort=s.get("reasoning_effort", ""),
                created_at=s.get("created_at", ""),
                last_used_at=s.get("last_used_at", ""),
            )
        channels[channel_id] = ChannelState(sessions=sessions, sticky=dict(sticky))

    fs = FileState(
        version=version,
        channels=channels,
        dm_bindings=dict(dm_bindings),
        runtime_options_global=runtime_options_global,
        runtime_options_channels=runtime_options_channels,
    )
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
            repo_name=_normalize_repo_name(ch.get("repo_name", "")),
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
                "reasoning_effort": s.reasoning_effort,
                "created_at": s.created_at,
                "last_used_at": s.last_used_at,
            }
        channels[channel_id] = {
            "sessions": sessions,
            "sticky": ch.sticky,
        }
    runtime_global = {}
    for key, value in (state.runtime_options_global or {}).items():
        normalized = _normalize_runtime_option_value(str(key), value)
        if normalized is not None:
            runtime_global[str(key)] = normalized
    runtime_channels = {}
    for channel_id, values in (state.runtime_options_channels or {}).items():
        raw_values = values if isinstance(values, dict) else {}
        scoped: Dict[str, Any] = {}
        for key, value in raw_values.items():
            normalized = _normalize_runtime_option_value(str(key), value)
            if normalized is not None:
                scoped[str(key)] = normalized
        if scoped:
            runtime_channels[str(channel_id)] = scoped
    return {
        "version": state.version,
        "channels": channels,
        "dm_bindings": state.dm_bindings,
        "runtime_options_global": runtime_global,
        "runtime_options_channels": runtime_channels,
    }


def utc_now_iso() -> str:
    """Return current UTC time in ISO8601 format."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _normalize_repo_name(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        return pathutil.normalize_repo_name(raw)
    except ValueError:
        return raw.lower()


def _normalize_runtime_option_value(key: str, value: Any) -> Any:
    token = (key or "").strip()
    if token in {"run_heartbeat_seconds", "run_completion_min_seconds"}:
        try:
            parsed = int(value)
        except Exception:
            return None
        if 1 <= parsed <= 86400:
            return parsed
        return None
    if token == "show_reasoning_details":
        return _normalize_bool(value)
    return None


def _normalize_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        if value in (0, 1):
            return bool(value)
        return None
    if isinstance(value, str):
        token = value.strip().lower()
        if token in _BOOL_TRUE:
            return True
        if token in _BOOL_FALSE:
            return False
    return None
