"""Multi-agent dispatch orchestrator: task branch lifecycle + agent fan-out."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from typing import TYPE_CHECKING, List, Optional

from ..agents.base import Options
from ..agents.factory import build_backend
from ..services.worktree import WorktreeError, WorktreeManager
from .output import AgentResult, DispatchOutputHandler
from .parser import DispatchSpec

if TYPE_CHECKING:
    from ..config import Config
    from ..platform.transport import ResponseSink
    from ..sessions.coordinator import SessionCoordinator

_log = logging.getLogger(__name__)

_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]")
_TASK_BRANCH_PREFIX = "task/"


class OrchestratorError(Exception):
    """Raised when orchestration cannot proceed."""


class Orchestrator:
    """Drive multi-agent dispatch: task branch creation, planning, fan-out."""

    def __init__(
        self,
        cfg: "Config",
        wt_manager: WorktreeManager,
        coordinator: "SessionCoordinator",
    ) -> None:
        self._cfg = cfg
        self._wt_manager = wt_manager
        self._coordinator = coordinator

    async def run(
        self,
        spec: DispatchSpec,
        channel_id: str,
        session: str,
        repo_path: str,
        repo_name: str,
        sink: "ResponseSink",
    ) -> None:
        """Entry point called by the router when a dispatch spec is detected."""
        output_handler = DispatchOutputHandler(self._cfg.dispatch.output_mode, sink)

        # Resolve or create task branch
        task_branch = self._coordinator.get_task_branch(channel_id, session)
        if not task_branch:
            task_branch = _make_task_branch_name(repo_name)

        # Orchestrated: Claude plans first, workers receive the plan
        plan_text = ""
        if spec.is_orchestrated:
            plan_text, task_branch = await self._run_planning_step(
                task_branch, repo_path, repo_name, spec, sink, output_handler
            )
            if plan_text is None:
                # planning step failed
                return
        else:
            # No planning step: ensure the task branch exists as a base for workers.
            try:
                task_branch = await self._ensure_task_branch(task_branch, repo_path)
            except OrchestratorError as exc:
                await sink.send(f"Dispatch error: {exc}")
                return

        # Persist task branch now that it's been created
        self._coordinator.update_task_branch(channel_id, session, task_branch)

        # Workers: all agents except claude when orchestrated
        workers = [a for a in spec.agents if not (spec.is_orchestrated and a == "claude")]

        # Build per-worker prompt (append plan if available)
        worker_prompt = spec.prompt
        if plan_text:
            worker_prompt = f"{spec.prompt}\n\nOrchestrator plan:\n{plan_text}".strip()

        if not workers:
            # claude-only dispatch with is_orchestrated – shouldn't happen, but guard
            return

        if spec.is_fanout and len(workers) > 1:
            tasks = [
                self._run_worker(agent, repo_path, task_branch, worker_prompt, output_handler)
                for agent in workers
            ]
            results: List[AgentResult] = list(await asyncio.gather(*tasks))
        else:
            results = []
            for agent in workers:
                result = await self._run_worker(agent, repo_path, task_branch, worker_prompt, output_handler)
                results.append(result)

        await output_handler.on_all_done(results)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _run_planning_step(
        self,
        task_branch: str,
        repo_path: str,
        repo_name: str,
        spec: DispatchSpec,
        sink: "ResponseSink",
        handler: DispatchOutputHandler,
    ):
        """Run Claude as orchestrator on the task branch. Returns (plan_text, task_branch)."""
        worker_agents = [a for a in spec.agents if a != "claude"]
        plan_prompt = (
            self._cfg.dispatch.plan_prompt
            .replace("{{USER_REQUEST}}", spec.prompt)
            .replace("{{AGENTS}}", ", ".join(worker_agents))
        )

        await handler.on_agent_start("claude")

        # Task branch is the planning branch
        try:
            task_branch = await self._ensure_task_branch(task_branch, repo_path)
        except OrchestratorError as exc:
            await sink.send(f"Dispatch error: {exc}")
            return None, task_branch

        result = await self._run_backend("claude", repo_path, task_branch, plan_prompt, branch_is_base=True)
        await handler.on_agent_done(result)

        if not result.success:
            await sink.send(f"Planning step failed: {result.error or 'unknown error'}")
            return None, task_branch

        return result.summary, task_branch

    async def _ensure_task_branch(self, task_branch: str, repo_path: str) -> str:
        """Create a worktree on the task branch, returning the branch name."""
        try:
            wt_path = await self._wt_manager.create(
                repo_path,
                _branch_to_slug(task_branch),
                branch_name=task_branch,
            )
            # Remove the worktree immediately — we just needed the branch created.
            # Agents get their own forked worktrees from this branch.
            await self._wt_manager.remove(wt_path)
        except WorktreeError as exc:
            raise OrchestratorError(str(exc)) from exc
        return task_branch

    async def _run_worker(
        self,
        agent: str,
        repo_path: str,
        task_branch: str,
        prompt: str,
        handler: DispatchOutputHandler,
    ) -> AgentResult:
        """Run a single worker agent on a fork of the task branch."""
        await handler.on_agent_start(agent)
        result = await self._run_backend(
            agent, repo_path, task_branch, prompt, branch_is_base=False
        )
        await handler.on_agent_done(result)
        return result

    async def _run_backend(
        self,
        agent: str,
        repo_path: str,
        base_or_task_branch: str,
        prompt: str,
        branch_is_base: bool,
    ) -> AgentResult:
        """
        Run one agent backend.

        branch_is_base=True  → run ON the given branch (for planning step)
        branch_is_base=False → create a fork of the branch for the worker
        """
        try:
            backend = build_backend(self._cfg, agent)
        except ValueError as exc:
            return AgentResult(agent=agent, success=False, error=str(exc))

        slug = _branch_to_slug(base_or_task_branch)
        if branch_is_base:
            # For planning: agent runs directly on the task branch (no fork)
            worker_branch = base_or_task_branch
            try:
                wt_path = await self._wt_manager.create(
                    repo_path,
                    f"{slug}-{agent}",
                    branch_name=worker_branch,
                )
            except WorktreeError as exc:
                return AgentResult(agent=agent, success=False, error=str(exc))
        else:
            # For workers: fork from the task branch
            worker_branch = f"{base_or_task_branch}-{agent}"
            try:
                wt_path = await self._wt_manager.create(
                    repo_path,
                    f"{slug}-{agent}",
                    base_branch=base_or_task_branch,
                    branch_name=worker_branch,
                )
            except WorktreeError as exc:
                return AgentResult(agent=agent, success=False, error=str(exc))

        done_event = asyncio.Event()
        rc_holder: list[int] = [1]
        output_lines: list[str] = []

        async def on_exit(err: Optional[BaseException], rc: int) -> None:
            rc_holder[0] = rc
            done_event.set()

        async def on_output(text: str) -> None:
            output_lines.append(text)

        try:
            args = backend.build_start_args(wt_path, prompt, "", "")
            await backend.run(Options(
                repo_path=wt_path,
                args=args,
                env={},
                on_exit=on_exit,
                on_output=on_output,
            ))
            await done_event.wait()

            rc = rc_holder[0]
            success = (rc == 0)
            files_changed = 0
            if success:
                files_changed = await _count_changed_files(wt_path, base_or_task_branch)
            summary = "\n".join(output_lines[-3:]) if output_lines else ""
            return AgentResult(
                agent=agent,
                success=success,
                files_changed=files_changed,
                summary=summary,
            )
        except Exception as exc:
            _log.warning("orchestrator.agent_failed", extra={"agent": agent, "error": str(exc)})
            return AgentResult(agent=agent, success=False, error=str(exc))
        finally:
            await self._wt_manager.remove(wt_path)


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------

def _make_task_branch_name(repo_name: str) -> str:
    slug = _SAFE_RE.sub("-", repo_name or "repo")[:30].strip("-") or "repo"
    ts = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    return f"{_TASK_BRANCH_PREFIX}{slug}/{ts}"


def _branch_to_slug(branch: str) -> str:
    return _SAFE_RE.sub("-", branch or "branch")[:40].strip("-") or "branch"


async def _count_changed_files(wt_path: str, base_branch: str) -> int:
    """Count files changed in wt_path relative to base_branch."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "git", "-C", wt_path, "diff", "--name-only", base_branch, "HEAD",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode != 0:
            return 0
        lines = [l for l in stdout.decode("utf-8", errors="replace").splitlines() if l.strip()]
        return len(lines)
    except Exception:
        return 0
