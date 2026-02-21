"""Session coordinator combining queue and session state."""

from __future__ import annotations

from typing import Any, Optional

from . import config as cfgmod
from .queue import Manager
from .router_helpers import PendingConflict
from .session_service import SessionService
from .state import Store


class SessionCoordinator:
    """Coordinate queued jobs with session state tracking."""

    def __init__(
        self,
        state: Store,
        cfg: cfgmod.Config,
        queue: Optional[Manager] = None,
        sessions: Optional[SessionService] = None,
    ) -> None:
        self._queue = queue or Manager()
        self._sessions = sessions or SessionService(state, cfg)

    async def enqueue(self, channel_id: str, session: str, job):
        return await self._queue.enqueue(channel_id, session, job)

    async def snapshot(self, channel_id: str):
        return await self._queue.snapshot(channel_id)

    async def snapshot_all(self):
        return await self._queue.snapshot_all()

    async def cancel(self, channel_id: str, job_id: str) -> bool:
        return await self._queue.cancel(channel_id, job_id)

    async def last_job(self, channel_id: str):
        return await self._queue.last_job(channel_id)

    async def rerun(self, channel_id: str) -> Optional[str]:
        record = await self._queue.last_job(channel_id)
        if not record:
            return None
        _, job_id, _ = await self._queue.enqueue(channel_id, record.session, record.job)
        return job_id

    async def set_active(self, channel_id: str, session: str, proc: Any) -> None:
        await self._sessions.set_active(channel_id, session, proc)

    async def clear_active(self, channel_id: str, session: str) -> None:
        await self._sessions.clear_active(channel_id, session)

    async def get_active(self, channel_id: str, session: str) -> Optional[Any]:
        return await self._sessions.get_active(channel_id, session)

    async def has_active(self, channel_id: str) -> bool:
        return await self._sessions.has_active(channel_id)

    async def set_pending_conflict(self, channel_id: str, session: str, conflict: PendingConflict) -> None:
        await self._sessions.set_pending_conflict(channel_id, session, conflict)

    async def consume_pending(self, channel_id: str, session: str) -> Optional[PendingConflict]:
        return await self._sessions.consume_pending(channel_id, session)

    async def reset_session(self, channel_id: str, session: str) -> bool:
        return await self._sessions.reset_session(channel_id, session)

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
        self._sessions.update_state(channel_id, session, repo_name, repo_path, thread_id, model, reasoning_effort)

    def session_model(self, channel_id: str, session: str) -> str:
        return self._sessions.session_model(channel_id, session)

    def session_reasoning_effort(self, channel_id: str, session: str) -> str:
        return self._sessions.session_reasoning_effort(channel_id, session)

    def set_session_model(
        self,
        channel_id: str,
        session: str,
        repo_name: str,
        repo_path: str,
        model: str,
        reasoning_effort: str,
    ) -> None:
        self._sessions.set_session_model(channel_id, session, repo_name, repo_path, model, reasoning_effort)

    def update_activity(self, channel_id: str, session: str) -> None:
        self._sessions.update_activity(channel_id, session)

    def get_activity(self, channel_id: str, session: str) -> Optional[str]:
        return self._sessions.get_activity(channel_id, session)

    def current_session_for_user(self, user_id: str, channel_id: str) -> str:
        return self._sessions.current_session_for_user(user_id, channel_id)

    def set_sticky(self, channel_id: str, user_id: str, session: str) -> None:
        self._sessions.set_sticky(channel_id, user_id, session)
