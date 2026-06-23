"""Git worktree lifecycle management for session isolation."""

import asyncio
import logging
import os
import re
import shutil
import time
from typing import List

_log = logging.getLogger(__name__)

_SAFE_SLUG_RE = re.compile(r"[^A-Za-z0-9._-]")
_SESSION_BRANCH_PREFIX = "session/"
_TASK_BRANCH_PREFIX = "task/"
_MANAGED_PREFIXES = (_SESSION_BRANCH_PREFIX, _TASK_BRANCH_PREFIX)


class WorktreeError(Exception):
    """Raised when a git worktree operation fails."""


class WorktreeManager:
    """Create, remove, and prune git worktrees for session isolation."""

    def __init__(self, base_dir: str, max_per_repo: int, cleanup_on_end: str) -> None:
        self._base_dir = base_dir or ""
        self._max_per_repo = max(1, max_per_repo)
        self._cleanup_on_end = cleanup_on_end or "remove"

    @property
    def cleanup_on_end(self) -> str:
        return self._cleanup_on_end

    async def create(
        self,
        repo_path: str,
        session_key: str,
        base_branch: str = "",
        branch_name: str = "",
    ) -> str:
        """Create a new git worktree for (repo_path, session_key).

        Returns the absolute path to the worktree directory.
        Raises WorktreeError on failure or if max_per_repo is reached.

        base_branch: when set, fork the new branch from this ref instead of HEAD.
        branch_name: when set, use this exact branch name instead of the auto-generated one.
        """
        count = await self.count_for_repo(repo_path)
        if count >= self._max_per_repo:
            raise WorktreeError(
                f"max worktrees ({self._max_per_repo}) reached for {repo_path}"
            )

        slug = _safe_slug(session_key)
        branch = branch_name or f"{_SESSION_BRANCH_PREFIX}{slug}/{_timestamp()}"
        wt_path = self._worktree_path(repo_path, slug)

        await _worktree_add(repo_path, branch, wt_path, base_branch)
        return wt_path

    async def remove(self, worktree_path: str) -> None:
        """Remove a worktree created by create(). Best-effort; logs on failure."""
        if not worktree_path:
            return
        repo_path = _find_repo_for_worktree(worktree_path)
        if repo_path:
            try:
                await _git(repo_path, ["worktree", "remove", "--force", worktree_path])
            except WorktreeError as exc:
                _log.warning("worktree.remove_failed", extra={"path": worktree_path, "error": str(exc)})
        if os.path.isdir(worktree_path):
            try:
                shutil.rmtree(worktree_path)
            except OSError as exc:
                _log.warning("worktree.rmtree_failed", extra={"path": worktree_path, "error": str(exc)})

    async def prune_stale(self, repo_path: str) -> None:
        """Run git worktree prune to clean up dead worktree refs. Best-effort."""
        try:
            await _git(repo_path, ["worktree", "prune", "--expire", "now"])
        except WorktreeError as exc:
            _log.warning("worktree.prune_failed", extra={"repo": repo_path, "error": str(exc)})

    async def count_for_repo(self, repo_path: str) -> int:
        """Count managed worktrees (session/ or task/ branches) for a repo."""
        lines = await _git_output(repo_path, ["worktree", "list", "--porcelain"])
        return _count_managed_worktrees(lines)

    def _worktree_path(self, repo_path: str, slug: str) -> str:
        repo_abs = os.path.realpath(repo_path)
        basename = os.path.basename(repo_abs)
        name = f"{basename}-wt-{slug}"
        if self._base_dir:
            return os.path.join(self._base_dir, name)
        parent = os.path.dirname(repo_abs)
        return os.path.join(parent, name)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _worktree_add(repo_path: str, branch: str, wt_path: str, base_branch: str) -> None:
    """Run git worktree add, recovering from stale directory and existing branch."""
    # Clean up orphaned directory left by a previous crashed session.
    if os.path.isdir(wt_path):
        _log.warning("worktree.stale_dir", extra={"path": wt_path})
        try:
            await _git(repo_path, ["worktree", "remove", "--force", wt_path])
        except WorktreeError:
            pass
        if os.path.isdir(wt_path):
            shutil.rmtree(wt_path, ignore_errors=True)

    args_create = ["worktree", "add", "-f", "-b", branch, wt_path]
    if base_branch:
        args_create.append(base_branch)
    try:
        await _git(repo_path, args_create)
        return
    except WorktreeError as exc:
        if "already exists" not in str(exc):
            raise

    # Branch already exists (left from a previous run) — check it out instead.
    _log.warning("worktree.branch_exists", extra={"branch": branch})
    args_checkout = ["worktree", "add", "-f", wt_path, branch]
    await _git(repo_path, args_checkout)


def _safe_slug(session_key: str, max_len: int = 40) -> str:
    slug = _SAFE_SLUG_RE.sub("-", session_key or "session")
    return slug[:max_len].strip("-") or "session"


def _timestamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S", time.gmtime())


def _find_repo_for_worktree(worktree_path: str) -> str:
    """Walk upward from a worktree sibling to find its git repo."""
    parent = os.path.dirname(os.path.realpath(worktree_path))
    try:
        entries = list(os.scandir(parent))
    except OSError:
        return ""
    for entry in entries:
        if entry.is_dir() and entry.path != os.path.realpath(worktree_path):
            git_dir = os.path.join(entry.path, ".git")
            if os.path.isdir(git_dir):
                return entry.path
    return ""


def _count_session_worktrees(porcelain_output: str) -> int:
    return _count_managed_worktrees(porcelain_output)


def _count_managed_worktrees(porcelain_output: str) -> int:
    count = 0
    for line in porcelain_output.splitlines():
        line = line.strip()
        if line.startswith("branch ") and any(p in line for p in _MANAGED_PREFIXES):
            count += 1
    return count


async def _git(repo_path: str, args: List[str]) -> None:
    """Run a git command in repo_path; raise WorktreeError on non-zero exit."""
    proc = await asyncio.create_subprocess_exec(
        "git", "-C", repo_path, *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr_bytes = await proc.communicate()
    if proc.returncode != 0:
        stderr = (stderr_bytes or b"").decode("utf-8", errors="replace").strip()
        raise WorktreeError(f"git {' '.join(args)} failed: {stderr}")


async def _git_output(repo_path: str, args: List[str]) -> str:
    """Run a git command and return stdout as a string."""
    proc = await asyncio.create_subprocess_exec(
        "git", "-C", repo_path, *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_bytes, stderr_bytes = await proc.communicate()
    if proc.returncode != 0:
        stderr = (stderr_bytes or b"").decode("utf-8", errors="replace").strip()
        raise WorktreeError(f"git {' '.join(args)} failed: {stderr}")
    return (stdout_bytes or b"").decode("utf-8", errors="replace")
