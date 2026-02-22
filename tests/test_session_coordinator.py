import asyncio
import time

from codebridge import config as cfgmod
from codebridge.routing.helpers import PendingConflict
from codebridge.sessions.coordinator import SessionCoordinator
from codebridge.sessions.state import Store


def _make_coordinator(tmp_path):
    cfg = cfgmod.Config()
    cfg.state.data_dir = str(tmp_path / "state")
    cfg.state.log_dir = str(tmp_path / "logs")
    store = Store(cfg.state.data_dir)
    return SessionCoordinator(store, cfg)


def test_coordinator_active_transitions(tmp_path):
    coord = _make_coordinator(tmp_path)

    async def run():
        await coord.set_active("chan", "sess", object())
        assert await coord.has_active("chan") is True
        await coord.clear_active("chan", "sess")
        assert await coord.has_active("chan") is False

    asyncio.run(run())


def test_coordinator_pending_conflict(tmp_path):
    coord = _make_coordinator(tmp_path)

    async def run():
        conflict = PendingConflict(
            repo_name="repo",
            session="sess",
            thread_id="thread",
            user_id="user",
            expires_at=time.time() + 60,
        )
        await coord.set_pending_conflict("chan", "sess", conflict)
        out = await coord.consume_pending("chan", "sess")
        assert out is not None
        assert out.repo_name == "repo"

    asyncio.run(run())


def test_coordinator_queue_rerun(tmp_path):
    coord = _make_coordinator(tmp_path)

    async def run():
        async def job():
            return None

        _, job_id, _ = await coord.enqueue("chan", "sess", job)
        rerun_id = await coord.rerun("chan")
        assert rerun_id is not None
        assert rerun_id != job_id

    asyncio.run(run())


def test_coordinator_reset_session(tmp_path):
    coord = _make_coordinator(tmp_path)
    coord.update_state("chan", "sess", "repo", "/tmp/repo", "thread-1", "", "")

    async def run():
        removed = await coord.reset_session("chan", "sess")
        assert removed is True

    asyncio.run(run())
