import asyncio
import time

from codebridge import config
from codebridge.router_helpers import PendingConflict
from codebridge.session_service import SessionService
from codebridge.state import Store


def test_session_service_pending_conflict_expired(tmp_path):
    store = Store(str(tmp_path))
    cfg = config.Config()
    service = SessionService(store, cfg)

    async def run():
        conflict = PendingConflict(
            repo_name="repo",
            session="default",
            thread_id="thread",
            user_id="user",
            expires_at=time.time() - 5,
        )
        await service.set_pending_conflict("chan", "default", conflict)
        assert await service.consume_pending("chan", "default") is None

    asyncio.run(run())


def test_session_service_active_tracking(tmp_path):
    store = Store(str(tmp_path))
    cfg = config.Config()
    service = SessionService(store, cfg)

    async def run():
        proc = object()
        await service.set_active("chan", "default", proc)
        assert await service.get_active("chan", "default") is proc
        assert await service.has_active("chan") is True
        await service.clear_active("chan", "default")
        assert await service.get_active("chan", "default") is None
        assert await service.has_active("chan") is False

    asyncio.run(run())
