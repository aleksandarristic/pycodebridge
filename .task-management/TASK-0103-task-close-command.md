# TASK-0103 — Task close command: `!c done` with PR and merge modes

**Branch:** `feature/dispatch-orchestrator`
**Status:** TODO

## Goal

Implement the `!c done` command that closes the active task branch for a channel session.
Supports two modes (configured via `cfg.dispatch.close_mode`, overridable per-invocation
with `--pr` or `--merge` flags).

---

## Modes

### `pr` mode
1. Push task branch to origin
2. Open draft PR via `gh pr create --draft` with title from last commit message
3. Post PR URL to channel: "📬 PR opened: <url> — review and merge on GitHub"
4. Clear `task_branch` from session state

### `merge` mode
1. Checkout main (or configured default branch)
2. Merge task branch: `git merge --no-ff task/<repo>/<timestamp>`
3. Push to origin
4. Delete task branch locally and remotely
5. Post to channel: "✅ Merged and pushed to main"
6. Clear `task_branch` from session state

Both modes delete all worker fork branches (`task/<repo>/<timestamp>-<agent>`) after
the task branch is handled.

---

## Changes

### `codebridge/dispatch/closer.py` (new file)

```python
class TaskCloseError(Exception): ...

class TaskCloser:
    def __init__(self, cfg: Config, coordinator: SessionCoordinator) -> None: ...

    async def close(
        self,
        channel_id: str,
        session: str,
        repo_path: str,
        mode: str,          # "pr" | "merge"
        sink: MessageSink,
    ) -> None:
        """
        Close the active task branch for this channel/session.
        Raises TaskCloseError if no active task branch exists.
        """
```

Uses `asyncio.create_subprocess_exec` for all git/gh calls (consistent with WorktreeManager).

### `codebridge/routing/router.py`

Parse `!c done [--pr|--merge]` in the command handler:
```python
if command == "done":
    mode = parse_close_flag(args) or cfg.dispatch.close_mode
    await self._task_closer.close(channel_id, session, repo_path, mode, sink)
    return
```

`Router.__init__` gains `task_closer: TaskCloser | None = None`; constructed in
`cmd/bridge.py` alongside the orchestrator.

### `cmd/bridge.py`

```python
from codebridge.dispatch.closer import TaskCloser
...
task_closer = TaskCloser(cfg, coordinator) if cfg.worktrees.enabled else None
router = Router(..., task_closer=task_closer)
```

---

## Tests

**File:** `tests/test_task_closer.py`

Use a real git repo in `tmp_path` (same approach as `test_worktree_manager.py`).

Cover:
- `pr` mode: task branch pushed, gh called with `--draft`, PR URL posted to sink, task_branch cleared
- `merge` mode: task branch merged into main, pushed, branch deleted, success message posted, task_branch cleared
- `--pr` flag overrides `close_mode: merge`
- `--merge` flag overrides `close_mode: pr`
- Error when no active task branch in session state
- Worker fork branches deleted in both modes
- Git failure mid-close posts error to channel (does not crash bot)

---

## Done criteria

- `!c done` closes task branch in configured mode
- `!c done --pr` / `!c done --merge` override per-invocation
- Task branch and all fork branches cleaned up after close
- Session state `task_branch` cleared after successful close
- All tests pass; no existing tests broken
