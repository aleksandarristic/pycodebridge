"""Session state, pending conflicts, and active process tracking."""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, Optional

from . import config as cfgmod
from .router_helpers import PendingConflict, set_sticky
from .state import Store, utc_now_iso


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

    def update_state(self, channel_id: str, session: str, repo_name: str, repo_path: str, thread_id: str, model: str) -> None:
        """Update persistent state for a session."""
        session = session or "default"

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
            sess.repo_name = repo_name
            sess.repo_path = repo_path
            sess.thread_id = thread_id
            if model:
                sess.model = model
            elif not sess.model and self._cfg.codex.model:
                sess.model = self._cfg.codex.model
            sess.last_used_at = utc_now_iso()
            ch.sessions[session] = sess
            fs.channels[channel_id] = ch

        self._state.update(mutator)

    def session_model(self, channel_id: str, session: str) -> str:
        """Return model override for a session or fallback to default."""
        state = self._state.load()
        ch = state.channels.get(channel_id)
        if ch:
            sess = ch.sessions.get(session or "default")
            if sess and sess.model:
                return sess.model
        return self._cfg.codex.model

    def set_session_model(self, channel_id: str, session: str, repo_name: str, repo_path: str, model: str) -> None:
        """Set a model override for a session."""
        state = self._state.load()
        thread_id = ""
        ch = state.channels.get(channel_id)
        if ch:
            sess = ch.sessions.get(session or "default")
            if sess:
                thread_id = sess.thread_id
        self.update_state(channel_id, session, repo_name, repo_path, thread_id, model)

    def current_session_for_user(self, user_id: str, channel_id: str) -> str:
        """Return sticky session selection for a user or default."""
        state = self._state.load()
        ch = state.channels.get(channel_id)
        if ch and user_id:
            sess = ch.sticky.get(user_id)
            if sess:
                return sess
        return "default"

    def set_sticky(self, channel_id: str, user_id: str, session: str) -> None:
        """Set sticky session selection for a user."""
        self._state.update(lambda fs: set_sticky(fs, channel_id, user_id, session))
