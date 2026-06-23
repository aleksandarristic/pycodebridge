"""Session state, pending conflicts, and active process tracking."""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, Optional

from .. import config as cfgmod
from ..routing.helpers import DEFAULT_SESSION, PendingConflict, normalize_session, set_sticky
from .state import Store, utc_now_iso
from ..util import path as pathutil


class SessionService:
    """Manage session state updates and in-memory process tracking."""

    def __init__(self, state: Store, cfg: cfgmod.Config) -> None:
        self._state = state
        self._cfg = cfg
        self._lock = asyncio.Lock()
        self._active: Dict[str, Dict[str, Any]] = {}
        self._pending: Dict[str, PendingConflict] = {}
        self._activity: Dict[str, Dict[str, float]] = {}

    async def set_active(self, channel_id: str, session: str, proc: Any) -> None:
        """Track a running process for a session."""
        async with self._lock:
            if channel_id not in self._active:
                self._active[channel_id] = {}
            self._active[channel_id][session] = proc

    async def clear_active(self, channel_id: str, session: str) -> None:
        """Clear the running process for a session."""
        async with self._lock:
            if channel_id in self._active:
                self._active[channel_id].pop(session, None)

    async def get_active(self, channel_id: str, session: str) -> Optional[Any]:
        """Return the running process for a session, if any."""
        async with self._lock:
            return self._active.get(channel_id, {}).get(session)

    async def has_active(self, channel_id: str) -> bool:
        """Return True if any session is active in a channel."""
        async with self._lock:
            if channel_id in self._active:
                return any(self._active[channel_id].values())
        return False

    async def active_sessions(self, channel_id: str) -> list[str]:
        """Return active session names for a channel."""
        async with self._lock:
            active = self._active.get(channel_id, {})
            names = [name for name, proc in active.items() if proc is not None]
        return sorted(names)

    def update_activity(self, channel_id: str, session: str) -> None:
        """Record last output time for a session."""
        if channel_id not in self._activity:
            self._activity[channel_id] = {}
        self._activity[channel_id][session] = time.time()

    def get_activity(self, channel_id: str, session: str) -> Optional[str]:
        """Return last output time for a session."""
        ts = self._activity.get(channel_id, {}).get(session)
        if not ts:
            return None
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))

    async def set_pending_conflict(self, channel_id: str, session: str, conflict: PendingConflict) -> None:
        """Store a pending conflict for start/replace."""
        async with self._lock:
            self._pending[f"{channel_id}:{session}"] = conflict

    async def consume_pending(self, channel_id: str, session: str) -> Optional[PendingConflict]:
        """Consume a pending conflict if present and not expired."""
        async with self._lock:
            if session:
                key = f"{channel_id}:{session}"
                conflict = self._pending.pop(key, None)
            else:
                conflict = None
                for key in list(self._pending.keys()):
                    if key.startswith(f"{channel_id}:"):
                        conflict = self._pending.pop(key, None)
                        break
        if not conflict:
            return None
        if conflict.expires_at < time.time():
            return None
        return conflict

    async def reset_session(self, channel_id: str, session: str) -> bool:
        """Reset in-memory and persistent context for a single session."""
        async with self._lock:
            active = self._active.get(channel_id)
            if active is not None:
                active.pop(session, None)
                if not active:
                    self._active.pop(channel_id, None)
            self._pending.pop(f"{channel_id}:{session}", None)
            activity = self._activity.get(channel_id)
            if activity is not None:
                activity.pop(session, None)
                if not activity:
                    self._activity.pop(channel_id, None)

        removed = False

        def mutator(fs):
            nonlocal removed
            ch = fs.channels.get(channel_id)
            if ch is None:
                return
            if session in ch.sessions:
                removed = True
                del ch.sessions[session]
            fs.channels[channel_id] = ch

        self._state.update(mutator)
        return removed

    async def migrate_channel_scope(self, from_channel_id: str, to_channel_id: str) -> bool:
        """Move runtime and persisted state from one channel scope key to another."""
        if not from_channel_id or not to_channel_id or from_channel_id == to_channel_id:
            return False
        changed = False

        async with self._lock:
            from_active = self._active.pop(from_channel_id, None)
            if from_active is not None:
                target = self._active.setdefault(to_channel_id, {})
                for session, proc in from_active.items():
                    if session not in target:
                        target[session] = proc
                changed = True

            from_activity = self._activity.pop(from_channel_id, None)
            if from_activity is not None:
                target_activity = self._activity.setdefault(to_channel_id, {})
                for session, ts in from_activity.items():
                    if session not in target_activity:
                        target_activity[session] = ts
                changed = True

            pending_prefix = f"{from_channel_id}:"
            for key in list(self._pending.keys()):
                if not key.startswith(pending_prefix):
                    continue
                suffix = key[len(pending_prefix) :]
                target_key = f"{to_channel_id}:{suffix}"
                conflict = self._pending.pop(key)
                if target_key not in self._pending:
                    self._pending[target_key] = conflict
                changed = True

        snapshot = self._state.load()
        if from_channel_id not in snapshot.channels and from_channel_id not in snapshot.runtime_options_channels:
            return changed

        state_changed = False

        def mutator(fs):
            nonlocal state_changed
            from_ch = fs.channels.get(from_channel_id)
            if from_ch is not None:
                to_ch = fs.channels.get(to_channel_id)
                if to_ch is None:
                    fs.channels[to_channel_id] = from_ch
                else:
                    for session, sess in from_ch.sessions.items():
                        if session not in to_ch.sessions:
                            to_ch.sessions[session] = sess
                    for user_id, sticky_session in from_ch.sticky.items():
                        if user_id not in to_ch.sticky:
                            to_ch.sticky[user_id] = sticky_session
                    fs.channels[to_channel_id] = to_ch
                fs.channels.pop(from_channel_id, None)
                state_changed = True

            from_opts = fs.runtime_options_channels.pop(from_channel_id, None)
            if from_opts is not None:
                to_opts = fs.runtime_options_channels.get(to_channel_id)
                if to_opts is None:
                    fs.runtime_options_channels[to_channel_id] = dict(from_opts)
                else:
                    for key, value in from_opts.items():
                        if key not in to_opts:
                            to_opts[key] = value
                    fs.runtime_options_channels[to_channel_id] = to_opts
                state_changed = True

        self._state.update(mutator)
        return changed or state_changed

    def update_state(
        self,
        channel_id: str,
        session: str,
        repo_name: str,
        repo_path: str,
        thread_id: str,
        model: str,
        reasoning_effort: str,
    ) -> None:
        """Update persistent state for a session."""
        session = _normalize_session_default(session)
        try:
            repo_name = pathutil.normalize_repo_name(repo_name)
        except ValueError:
            repo_name = (repo_name or "").strip().lower()

        def mutator(fs):
            ch = fs.channels.get(channel_id)
            if ch is None:
                from .state import ChannelState

                ch = ChannelState()
                fs.channels[channel_id] = ch
            sess = ch.sessions.get(session)
            if sess is None:
                from .state import SessionState

                sess = SessionState(repo_name=repo_name, repo_path=repo_path, thread_id=thread_id)
            if not sess.created_at:
                sess.created_at = utc_now_iso()
            if repo_name:
                sess.repo_name = repo_name
            if repo_path:
                sess.repo_path = repo_path
            if thread_id:
                sess.thread_id = thread_id
            if model and (sess.model or model != self._cfg.codex.model):
                sess.model = model
            if reasoning_effort and (
                sess.reasoning_effort or reasoning_effort != self._cfg.codex.model_reasoning_effort
            ):
                sess.reasoning_effort = reasoning_effort
            sess.last_used_at = utc_now_iso()
            ch.sessions[session] = sess
            fs.channels[channel_id] = ch

        self._state.update(mutator)

    def clear_session_thread(self, channel_id: str, session: str) -> bool:
        """Clear stored thread id for a session; return True when changed."""
        session = _normalize_session_default(session)
        cleared = False

        def mutator(fs):
            nonlocal cleared
            ch = fs.channels.get(channel_id)
            if ch is None:
                return
            sess = ch.sessions.get(session)
            if sess is None:
                return
            if sess.thread_id:
                sess.thread_id = ""
                ch.sessions[session] = sess
                fs.channels[channel_id] = ch
                cleared = True

        self._state.update(mutator)
        return cleared

    def session_model(self, channel_id: str, session: str) -> str:
        """Return model override for a session or fallback to default."""
        session = _normalize_session_default(session)
        state = self._state.load()
        ch = state.channels.get(channel_id)
        if ch:
            sess = ch.sessions.get(session)
            if sess and sess.model:
                return sess.model
        return self._cfg.codex.model

    def session_reasoning_effort(self, channel_id: str, session: str) -> str:
        """Return reasoning effort override for a session or fallback to default."""
        session = _normalize_session_default(session)
        state = self._state.load()
        ch = state.channels.get(channel_id)
        if ch:
            sess = ch.sessions.get(session)
            if sess and sess.reasoning_effort:
                return sess.reasoning_effort
        return self._cfg.codex.model_reasoning_effort

    def set_session_model(
        self,
        channel_id: str,
        session: str,
        repo_name: str,
        repo_path: str,
        model: str,
        reasoning_effort: str,
        *,
        clear_model: bool = False,
        clear_reasoning: bool = False,
    ) -> None:
        """Set model and reasoning overrides for a session."""
        session = _normalize_session_default(session)
        try:
            repo_name = pathutil.normalize_repo_name(repo_name)
        except ValueError:
            repo_name = (repo_name or "").strip().lower()

        def mutator(fs):
            ch = fs.channels.get(channel_id)
            if ch is None:
                from .state import ChannelState

                ch = ChannelState()
                fs.channels[channel_id] = ch
            sess = ch.sessions.get(session)
            if sess is None:
                from .state import SessionState

                sess = SessionState(repo_name=repo_name, repo_path=repo_path, thread_id="")
            if not sess.created_at:
                sess.created_at = utc_now_iso()
            if repo_name:
                sess.repo_name = repo_name
            if repo_path:
                sess.repo_path = repo_path
            if clear_model:
                sess.model = ""
            elif model:
                sess.model = model
            if clear_reasoning:
                sess.reasoning_effort = ""
            elif reasoning_effort:
                sess.reasoning_effort = reasoning_effort
            sess.last_used_at = utc_now_iso()
            ch.sessions[session] = sess
            fs.channels[channel_id] = ch

        self._state.update(mutator)

    def session_backend(self, channel_id: str, session: str) -> str:
        """Return the backend name for a session, falling back to the configured default."""
        session = _normalize_session_default(session)
        state = self._state.load()
        ch = state.channels.get(channel_id)
        if ch:
            sess = ch.sessions.get(session)
            if sess and sess.backend:
                return sess.backend
        return self._cfg.agent.default_backend

    def set_session_backend(
        self,
        channel_id: str,
        session: str,
        backend: str,
    ) -> dict:
        """Switch backend for a session; clears thread_id and resets model/effort."""
        session = _normalize_session_default(session)
        cleared_thread = False
        cleared_model = ""
        cleared_effort = ""

        def mutator(fs):
            nonlocal cleared_thread, cleared_model, cleared_effort
            ch = fs.channels.get(channel_id)
            if ch is None:
                from .state import ChannelState
                ch = ChannelState()
                fs.channels[channel_id] = ch
            sess = ch.sessions.get(session)
            if sess is None:
                from .state import SessionState
                sess = SessionState(repo_name="", repo_path="", thread_id="")
                ch.sessions[session] = sess
            if sess.thread_id:
                cleared_thread = True
                sess.thread_id = ""
            cleared_model = sess.model
            cleared_effort = sess.reasoning_effort
            sess.model = ""
            sess.reasoning_effort = ""
            sess.backend = backend
            ch.sessions[session] = sess
            fs.channels[channel_id] = ch

        self._state.update(mutator)
        return {
            "cleared_thread": cleared_thread,
            "cleared_model": cleared_model,
            "cleared_effort": cleared_effort,
        }

    def current_session_for_user(self, user_id: str, channel_id: str, default_session: str = DEFAULT_SESSION) -> str:
        """Return sticky session selection for a user or default."""
        state = self._state.load()
        ch = state.channels.get(channel_id)
        if ch and user_id:
            sess = ch.sticky.get(user_id)
            if sess:
                return sess
        return _normalize_session_default(default_session)

    def set_sticky(self, channel_id: str, user_id: str, session: str) -> None:
        """Set sticky session selection for a user."""
        self._state.update(lambda fs: set_sticky(fs, channel_id, user_id, _normalize_session_default(session)))

    def update_worktree_path(self, channel_id: str, session: str, path: str) -> None:
        """Persist the active worktree path for a session (empty string to clear)."""
        session = _normalize_session_default(session)

        def mutator(fs):
            from .state import ChannelState, SessionState
            ch = fs.channels.setdefault(channel_id, ChannelState())
            ss = ch.sessions.get(session)
            if ss is None:
                ss = SessionState(repo_name="", repo_path="", thread_id="")
                ch.sessions[session] = ss
            ss.worktree_path = path

        self._state.update(mutator)


def _normalize_session_default(session: str) -> str:
    raw = (session or "").strip()
    if not raw:
        return DEFAULT_SESSION
    try:
        return normalize_session(raw)
    except ValueError:
        return DEFAULT_SESSION
