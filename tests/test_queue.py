import asyncio

from codebridge.queue import Manager


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

        pos2, id2, fut2 = await mgr.enqueue("chan", "default", job2)
        assert pos2 == 1
        ok = await mgr.cancel("chan", id2)
        assert ok is True
        try:
            await fut2
        except Exception:
            pass

    asyncio.run(run())
