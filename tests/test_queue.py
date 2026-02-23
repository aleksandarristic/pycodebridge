import asyncio

from codebridge.sessions.queue import Manager


def test_queue_enqueue_and_cancel():
    async def run():
        mgr = Manager()
        ran = []

        async def job1():
            ran.append("job1")

        async def job2():
            await asyncio.sleep(0.05)
            ran.append("job2")

        pos1, id1, fut1 = await mgr.enqueue("chan", "default", job1)
        assert pos1 == 1
        await fut1
        assert ran == ["job1"]

        gate = asyncio.Event()

        async def blocker():
            await gate.wait()

        pos_block, _, fut_block = await mgr.enqueue("chan", "default", blocker)
        assert pos_block == 1

        # Yield once so blocker becomes active and job2 is truly queued behind it.
        await asyncio.sleep(0)

        pos2, id2, fut2 = await mgr.enqueue("chan", "default", job2)
        assert pos2 == 1

        snapshot = await mgr.snapshot("chan")
        assert len(snapshot) == 2
        assert snapshot[0].status == "running"
        assert snapshot[0].queued_at > 0
        assert snapshot[0].started_at > 0
        assert snapshot[1].status == "queued"
        assert snapshot[1].job_id == id2
        assert snapshot[1].queued_at > 0
        assert snapshot[1].started_at == 0

        ok = await mgr.cancel("chan", id2)
        assert ok is True
        try:
            await fut2
            assert False, "cancelled job future should raise"
        except RuntimeError as exc:
            assert str(exc) == "cancelled"

        gate.set()
        await fut_block

    asyncio.run(run())


def test_queue_worker_prunes_after_idle():
    async def run():
        mgr = Manager(worker_idle_seconds=0.1)

        async def job():
            return None

        _, _, fut = await mgr.enqueue("chan", "default", job)
        await fut
        # Let the worker hit idle timeout and exit.
        await asyncio.sleep(0.2)
        await mgr.snapshot_all()
        assert len(mgr._workers) == 0

    asyncio.run(run())


def test_queue_rekey_channel_moves_worker_and_last_job():
    async def run():
        mgr = Manager()
        gate = asyncio.Event()

        async def blocker():
            await gate.wait()

        _, _, fut = await mgr.enqueue("legacy-thread", "default", blocker)
        await asyncio.sleep(0)

        changed = await mgr.rekey_channel("legacy-thread", "discord:parent:legacy-thread")
        assert changed is True
        assert await mgr.snapshot("legacy-thread") == []
        snapshot = await mgr.snapshot("discord:parent:legacy-thread")
        assert len(snapshot) == 1
        assert snapshot[0].status == "running"

        assert await mgr.last_job("legacy-thread") is None
        assert await mgr.last_job("discord:parent:legacy-thread") is not None
        gate.set()
        await fut

    asyncio.run(run())
