# TASK-0097 — Wire WorktreeManager lifecycle into session flow

**Branch:** `feature/worktree-session-isolation`
**Depends on:** TASK-0094, TASK-0095, TASK-0096
**Status:** TODO

## Goal

Make worktrees actually activate: create one before each agent run, pass its path as
`repo_path` to `AgentBackend.run()`, persist it in `SessionState`, and remove it
when the run ends. Default-off (`worktrees.enabled: false`) so existing behaviour is
unchanged.

---

## Where agent runs are launched

The agent subprocess is started in `codebridge/routing/router.py`. Search for calls
to `AgentBackend.run(opts)` — there are two sites:

1. **`_run_start`** (or similar) — starts a new session with `build_start_args`
2. **`_run_resume`** (or similar) — resumes with `build_resume_args` / `build_resume_last_args`

The `opts.repo_path` passed to both is derived from the repo's path on disk
(e.g. `os.path.join(cfg.codex.code_root, repo_name)`).

Read the actual function names in `router.py` before implementing — the names above
are approximate.

---

## Changes

### `codebridge/services/worktree.py`

No change — already implemented in TASK-0095.

### `cmd/bridge.py` (startup)

On startup, after the config is loaded and before the bot starts, call
`prune_stale()` for each subdirectory of `codex.code_root` that is a git repo:

```python
if cfg.worktrees.enabled:
    wt_manager = WorktreeManager(
        base_dir=cfg.worktrees.base_dir,
        max_per_repo=cfg.worktrees.max_per_repo,
        cleanup_on_end=cfg.worktrees.cleanup_on_end,
    )
    for entry in os.scandir(cfg.codex.code_root):
        if entry.is_dir() and os.path.isdir(os.path.join(entry.path, ".git")):
            await wt_manager.prune_stale(entry.path)
```

Pass `wt_manager` (or `None` if `worktrees.enabled = false`) down to whatever
constructs the `Router` or `SessionCoordinator`.

### `codebridge/routing/router.py` — `_run_start` and `_run_resume`

Before calling `backend.run(opts)`, if a `WorktreeManager` is injected and
`cfg.worktrees.enabled`:

```python
# session_key is "<channel_id>-<session_name>"
if self._wt_manager is not None:
    try:
        worktree_path = await self._wt_manager.create(repo_path, session_key)
    except WorktreeError as exc:
        # surface the error to the user and abort the run
        await sink.send(f"Cannot start session: {exc}")
        return
    # persist the worktree path in state before the job runs
    self._coordinator.update_worktree_path(channel_id, session, worktree_path)
    effective_repo_path = worktree_path
else:
    effective_repo_path = repo_path
```

In the `on_exit` callback of `backend.run()`:

```python
async def on_exit(err, rc):
    if self._wt_manager is not None and worktree_path:
        if cfg.worktrees.cleanup_on_end == "remove":
            await self._wt_manager.remove(worktree_path)
            self._coordinator.update_worktree_path(channel_id, session, "")
        # "keep" and "pr" modes: leave worktree on disk; clear path from state
        # (pr mode: TODO — post-MVP, implement push+PR open here)
        else:
            self._coordinator.update_worktree_path(channel_id, session, "")
    # ... rest of existing on_exit logic
```

### `codebridge/sessions/service.py`

Add a method (mirroring the pattern of `set_session_backend`):

```python
def update_worktree_path(self, channel_id: str, session: str, path: str) -> None:
    """Persist the active worktree path for a session."""
    def _mutate(state: FileState) -> None:
        ch = state.channels.setdefault(channel_id, ChannelState())
        ss = ch.sessions.setdefault(session, SessionState(repo_name="", repo_path="", thread_id=""))
        ss.worktree_path = path
    self._store.update(_mutate)
```

### `codebridge/sessions/coordinator.py`

Delegate the new method:

```python
def update_worktree_path(self, channel_id: str, session: str, path: str) -> None:
    self._sessions.update_worktree_path(channel_id, session, path)
```

---

## Key invariants

- If `cfg.worktrees.enabled = false`, all code paths are identical to today — no
  worktree is created, `effective_repo_path == repo_path`.
- `worktree_path` in state is `""` when no worktree is active (between runs or after
  cleanup). It is non-empty only while the agent subprocess is running.
- Errors from `WorktreeManager.create()` are surfaced to the Discord channel and abort
  the run (do not leave a zombie session).
- Errors from `WorktreeManager.remove()` are only logged — never surface to Discord
  (the run already completed).

---

## Tests

**File:** `tests/test_worktree_lifecycle.py`

Use the fake backend / fake router harness that exists in `tests/` (look at existing
integration tests that exercise `Router` end-to-end).

| Test | What it checks |
|---|---|
| `test_worktree_created_before_run` | With `worktrees.enabled=true`, `WorktreeManager.create` called before backend |
| `test_worktree_path_stored_in_state` | `coordinator.update_worktree_path` called with path |
| `test_worktree_removed_on_clean_exit` | `remove()` called in `on_exit` when `cleanup_on_end=remove` |
| `test_worktree_kept_on_keep` | `remove()` not called when `cleanup_on_end=keep` |
| `test_worktree_create_error_aborts_run` | Error from `create()` → message to sink, no backend run |
| `test_no_worktree_when_disabled` | With `enabled=false`, `create()` never called, `repo_path` unchanged |
| `test_prune_called_on_startup` | `prune_stale()` called for each git repo in `code_root` at startup |

Use a `FakeWorktreeManager` in tests that records calls and returns a configurable
path or raises `WorktreeError`.

---

## Done criteria

- `worktrees.enabled: true` in config → worktree dir created, agent runs in it, dir removed after exit
- `worktrees.enabled: false` (default) → zero behaviour change, all existing tests still pass
- `worktree_path` in `SessionState` is non-empty during the run and `""` after
