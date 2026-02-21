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


def test_session_service_update_state_normalizes_repo_name(tmp_path):
    store = Store(str(tmp_path))
    cfg = config.Config()
    service = SessionService(store, cfg)

    service.update_state("chan", "default", "ProbablyFine", "/tmp/ProbablyFine", "thread", "", "")
    state = store.load()
    assert state.channels["chan"].sessions["default"].repo_name == "probablyfine"


def test_session_service_reset_session_clears_state_and_runtime(tmp_path):
    store = Store(str(tmp_path))
    cfg = config.Config()
    service = SessionService(store, cfg)
    service.update_state("chan", "default", "repo", "/tmp/repo", "thread-1", "", "")

    async def run():
        proc = object()
        await service.set_active("chan", "default", proc)
        service.update_activity("chan", "default")
        removed = await service.reset_session("chan", "default")
        assert removed is True
        assert await service.get_active("chan", "default") is None
        assert service.get_activity("chan", "default") is None

    asyncio.run(run())
    state = store.load()
    assert "default" not in state.channels["chan"].sessions


def test_session_service_update_state_preserves_existing_repo_context_on_empty_update(tmp_path):
    store = Store(str(tmp_path))
    cfg = config.Config()
    service = SessionService(store, cfg)
    service.update_state("chan", "default", "repo", "/tmp/repo", "thread-1", "", "")

    # This mirrors sticky-session selection paths that should not erase repo context.
    service.update_state("chan", "default", "", "", "", "", "")
    state = store.load()
    sess = state.channels["chan"].sessions["default"]
    assert sess.repo_name == "repo"
    assert sess.repo_path == "/tmp/repo"
    assert sess.thread_id == "thread-1"
