"""Task close: push task branch as PR or merge it into main."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, List

if TYPE_CHECKING:
    from ..config import Config
    from ..platform.transport import ResponseSink
    from ..sessions.coordinator import SessionCoordinator

_log = logging.getLogger(__name__)


class TaskCloseError(Exception):
    """Raised when the task close operation cannot proceed."""


class TaskCloser:
    """Close the active task branch for a channel session."""

    def __init__(self, cfg: "Config", coordinator: "SessionCoordinator") -> None:
        self._cfg = cfg
        self._coordinator = coordinator

    async def close(
        self,
        channel_id: str,
        session: str,
        repo_path: str,
        mode: str,
        sink: "ResponseSink",
    ) -> None:
        """Close the active task branch.

        mode: "pr" | "merge"
        Raises TaskCloseError when no active task branch exists.
        Posts status/result to sink.
        """
        task_branch = self._coordinator.get_task_branch(channel_id, session)
        if not task_branch:
            raise TaskCloseError("No active task branch. Start a dispatch with @agent first.")

        try:
            if mode == "merge":
                await self._merge(repo_path, task_branch, sink)
            else:
                await self._open_pr(repo_path, task_branch, sink)
        finally:
            await self._cleanup_worker_branches(repo_path, task_branch)
            self._coordinator.clear_task_branch(channel_id, session)

    # ------------------------------------------------------------------

    async def _open_pr(self, repo_path: str, task_branch: str, sink: "ResponseSink") -> None:
        """Push task branch and open a draft PR via gh."""
        # Push the branch
        await _git(repo_path, ["push", "origin", task_branch])

        # Get title from last commit
        title = await _git_output(repo_path, ["log", "-1", "--pretty=%s", task_branch])
        title = title.strip() or f"Dispatch task: {task_branch}"

        # Open draft PR
        pr_url = await _gh_output(repo_path, [
            "pr", "create",
            "--draft",
            "--head", task_branch,
            "--title", title,
            "--body", f"Created by pycodebridge dispatch.\n\nBranch: `{task_branch}`",
        ])
        pr_url = pr_url.strip()
        await sink.send(f"📬 PR opened: {pr_url} — review and merge on GitHub")

    async def _merge(self, repo_path: str, task_branch: str, sink: "ResponseSink") -> None:
        """Merge task branch into the default branch and push."""
        default_branch = await _default_branch(repo_path)
        await _git(repo_path, ["checkout", default_branch])
        await _git(repo_path, ["merge", "--no-ff", task_branch, "-m", f"Merge dispatch task {task_branch}"])
        await _git(repo_path, ["push", "origin", default_branch])
        # Delete task branch locally and remotely (best-effort)
        try:
            await _git(repo_path, ["branch", "-d", task_branch])
        except Exception:
            pass
        try:
            await _git(repo_path, ["push", "origin", "--delete", task_branch])
        except Exception:
            pass
        await sink.send(f"✅ Merged `{task_branch}` into `{default_branch}` and pushed.")

    async def _cleanup_worker_branches(self, repo_path: str, task_branch: str) -> None:
        """Delete local and remote worker branches (task_branch-<agent>). Best-effort."""
        try:
            out = await _git_output(repo_path, ["branch", "--list", f"{task_branch}-*"])
            branches = [b.strip().lstrip("* ") for b in out.splitlines() if b.strip()]
        except Exception:
            return
        for branch in branches:
            if not branch:
                continue
            try:
                await _git(repo_path, ["branch", "-D", branch])
            except Exception:
                pass
            try:
                await _git(repo_path, ["push", "origin", "--delete", branch])
            except Exception:
                pass


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

async def _git(repo_path: str, args: List[str]) -> None:
    proc = await asyncio.create_subprocess_exec(
        "git", "-C", repo_path, *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr_bytes = await proc.communicate()
    if proc.returncode != 0:
        stderr = (stderr_bytes or b"").decode("utf-8", errors="replace").strip()
        raise TaskCloseError(f"git {' '.join(args)} failed: {stderr}")


async def _git_output(repo_path: str, args: List[str]) -> str:
    proc = await asyncio.create_subprocess_exec(
        "git", "-C", repo_path, *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_bytes, _ = await proc.communicate()
    return (stdout_bytes or b"").decode("utf-8", errors="replace")


async def _gh_output(repo_path: str, args: List[str]) -> str:
    proc = await asyncio.create_subprocess_exec(
        "gh", *args,
        cwd=repo_path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_bytes, stderr_bytes = await proc.communicate()
    if proc.returncode != 0:
        stderr = (stderr_bytes or b"").decode("utf-8", errors="replace").strip()
        raise TaskCloseError(f"gh {' '.join(args)} failed: {stderr}")
    return (stdout_bytes or b"").decode("utf-8", errors="replace")


async def _default_branch(repo_path: str) -> str:
    """Return the default branch name (main or master)."""
    try:
        out = await _git_output(repo_path, ["symbolic-ref", "refs/remotes/origin/HEAD"])
        # refs/remotes/origin/main → main
        return out.strip().split("/")[-1] or "main"
    except Exception:
        return "main"


def parse_close_mode(args: str, default: str) -> str:
    """Parse --pr or --merge from args string; return default if neither present."""
    tokens = (args or "").split()
    if "--pr" in tokens:
        return "pr"
    if "--merge" in tokens:
        return "merge"
    return default
