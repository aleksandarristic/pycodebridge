# TASK-0095 — WorktreeManager service

**Branch:** `feature/worktree-session-isolation`
**Depends on:** TASK-0094 (WorktreeConfig)
**Status:** TODO

## Goal

Implement `codebridge/services/worktree.py` — the low-level service that creates,
removes, and prunes git worktrees. This is pure git plumbing; no session or router
logic yet. Subsequent tasks wire it into the session lifecycle.

---

## New file: `codebridge/services/worktree.py`

### Public API

```python
class WorktreeError(Exception):
    """Raised when a git worktree operation fails."""

class WorktreeManager:
    def __init__(
        self,
        base_dir: str,           # "" = use sibling-of-repo strategy
        max_per_repo: int,       # hard cap; enforced in create()
        cleanup_on_end: str,     # "remove" | "keep" | "pr"
    ) -> None: ...

    async def create(self, repo_path: str, session_key: str) -> str:
        """
        Create a new git worktree for (repo_path, session_key).
        Returns the absolute path to the worktree directory.
        Raises WorktreeError on failure or if max_per_repo is reached.
        """

    async def remove(self, worktree_path: str) -> None:
        """
        Remove a worktree created by create().
        Uses `git worktree remove --force <path>` then deletes the directory
        if still present. Logs and swallows errors (called from on_exit).
        """

    async def prune_stale(self, repo_path: str) -> None:
        """
        Run `git worktree prune` in repo_path to clean up dead worktree refs.
        Called once on startup per configured repo.
        """

    async def count_for_repo(self, repo_path: str) -> int:
        """
        Parse `git worktree list --porcelain` to count how many managed
        worktrees exist for this repo (i.e., whose branch matches
        'refs/heads/session/').
        """
```

### Worktree path strategy

**Branch name format:** `session/<safe-slug>/<yyyymmdd-hhmmss>`

Where `<safe-slug>` is `session_key` with any character outside `[A-Za-z0-9._-]`
replaced by `-`, truncated to 40 chars.

**Directory path:**
- If `base_dir` is set and non-empty: `<base_dir>/<repo_basename>-<safe-slug>/`
- Otherwise: `<parent of repo_path>/<repo_basename>-wt-<safe-slug>/`

Example: repo at `/repos/myapp`, session key `1234567890-default`:
- branch: `session/1234567890-default/20260623-141500`
- path: `/repos/myapp-wt-1234567890-default/`

### Git commands used (all via `asyncio.create_subprocess_exec`)

```
git -C <repo_path> worktree add -b <branch> <worktree_path>
git -C <repo_path> worktree remove --force <worktree_path>
git -C <repo_path> worktree prune
git -C <repo_path> worktree list --porcelain
```

Capture stdout+stderr, raise `WorktreeError` with stderr content if returncode != 0,
**except** in `remove()` and `prune_stale()` where failures are only logged (best effort).

### `max_per_repo` enforcement

In `create()`, call `count_for_repo()` before creating the worktree. If
`count >= self.max_per_repo`, raise `WorktreeError(f"max worktrees ({self.max_per_repo}) reached for {repo_path}")`.

### Imports

`asyncio`, `os`, `re`, `time`, `logging` — stdlib only, no new dependencies.

---

## Tests

**File:** `tests/test_worktree_manager.py`

Use `tmp_path` (pytest fixture) to create real git repos: `git init`, `git commit
--allow-empty -m init`. All tests use real git subprocess calls — no mocking of git.

Tests to cover:

| Test | What it checks |
|---|---|
| `test_create_makes_directory` | Worktree dir exists after `create()` |
| `test_create_branch_name_format` | Branch starts with `session/`, contains slug and timestamp |
| `test_create_path_sibling_strategy` | With empty `base_dir`, path is sibling of repo |
| `test_create_path_base_dir_strategy` | With `base_dir` set, path is under `base_dir` |
| `test_remove_deletes_directory` | Dir gone after `remove()` |
| `test_remove_is_idempotent` | Calling `remove()` on missing path doesn't raise |
| `test_prune_stale_runs_without_error` | `prune_stale()` completes on a clean repo |
| `test_max_per_repo_raises` | `WorktreeError` raised when `max_per_repo` reached |
| `test_count_for_repo` | Returns correct count after creating N worktrees |
| `test_create_bad_repo_path_raises` | `WorktreeError` on non-git directory |

---

## Done criteria

- All tests above pass with real git repos in `tmp_path`
- `WorktreeManager` imported cleanly from `codebridge.services.worktree`
- No changes to existing files except adding the new module to `services/__init__.py` if it has exports
