"""Per-channel async job queue manager."""

import asyncio
from collections import OrderedDict
from dataclasses import dataclass
from typing import Awaitable, Callable, Dict, Optional

Job = Callable[[], Awaitable[None]]


@dataclass
class JobRecord:
    """Record of a queued job used for reruns."""
    job: Job
    session: str
    label: str = ""


@dataclass
class JobStatus:
    """Snapshot of a job's queue status."""
    job_id: str
    session: str
    status: str
    position: int


class Manager:
    """Queue manager that serializes jobs per channel."""
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._workers: Dict[str, _Worker] = {}
        self._counter = 0
        self._last_jobs: Dict[str, JobRecord] = {}

    async def enqueue(self, channel_id: str, session: str, job: Job) -> tuple[int, str, asyncio.Future]:
        """Enqueue a job for a channel and return (position, job_id, future)."""
        async with self._lock:
            worker = self._workers.get(channel_id)
            if worker is None:
                worker = _Worker()
                self._workers[channel_id] = worker
                asyncio.create_task(worker.run())
            self._counter += 1
            job_id = f"job-{self._counter}"
            fut: asyncio.Future = asyncio.get_running_loop().create_future()
            pos = await worker.enqueue(_JobRequest(job_id, session, job, fut))
            self._last_jobs[channel_id] = JobRecord(job=job, session=session)
            return pos, job_id, fut

    async def snapshot(self, channel_id: str) -> list[JobStatus]:
        """Return a snapshot of queued/running jobs for a channel."""
        async with self._lock:
            worker = self._workers.get(channel_id)
            if worker is None:
                return []
            return await worker.snapshot()

    async def snapshot_all(self) -> Dict[str, list[JobStatus]]:
        """Return snapshots for all channels with queued/running jobs."""
        async with self._lock:
            items = list(self._workers.items())
        out: Dict[str, list[JobStatus]] = {}
        for channel_id, worker in items:
            statuses = await worker.snapshot()
            if statuses:
                out[channel_id] = statuses
        return out

    async def cancel(self, channel_id: str, job_id: str) -> bool:
        """Cancel a queued job by id."""
        async with self._lock:
            worker = self._workers.get(channel_id)
        if worker is None:
            return False
        return await worker.cancel(job_id)

    async def last_job(self, channel_id: str) -> Optional[JobRecord]:
        """Return the most recent enqueued job for a channel."""
        async with self._lock:
            return self._last_jobs.get(channel_id)


@dataclass
class _JobRequest:
    job_id: str
    session: str
    job: Job
    future: asyncio.Future
    cancelled: bool = False


class _Worker:
    """Internal worker that executes jobs sequentially."""
    def __init__(self) -> None:
        self._queue: asyncio.Queue[_JobRequest] = asyncio.Queue()
        self._pending: "OrderedDict[str, _JobRequest]" = OrderedDict()
        self._active: Optional[_JobRequest] = None
        self._lock = asyncio.Lock()

    async def enqueue(self, req: _JobRequest) -> int:
        """Enqueue a job request and return queue position."""
        async with self._lock:
            self._pending[req.job_id] = req
            self._queue.put_nowait(req)
            return len(self._pending)

    async def run(self) -> None:
        """Run queued jobs in order forever."""
        while True:
            req = await self._queue.get()
            async with self._lock:
                self._pending.pop(req.job_id, None)
                self._active = req
            try:
                if req.cancelled:
                    continue
                await req.job()
                if not req.future.done():
                    req.future.set_result(None)
            except Exception as exc:
                if not req.future.done():
                    req.future.set_exception(exc)
            finally:
                async with self._lock:
                    self._active = None
                self._queue.task_done()

    async def snapshot(self) -> list[JobStatus]:
        """Snapshot of current running and queued jobs."""
        async with self._lock:
            statuses: list[JobStatus] = []
            if self._active:
                statuses.append(JobStatus(job_id=self._active.job_id, session=self._active.session, status="running", position=0))
            for idx, req in enumerate(self._pending.values(), start=1):
                statuses.append(JobStatus(job_id=req.job_id, session=req.session, status="queued", position=idx))
            return statuses

    async def cancel(self, job_id: str) -> bool:
        """Cancel a queued job if present."""
        async with self._lock:
            req = self._pending.pop(job_id, None)
            if req is None:
                return False
            req.cancelled = True
            if not req.future.done():
                req.future.set_exception(RuntimeError("cancelled"))
            return True
