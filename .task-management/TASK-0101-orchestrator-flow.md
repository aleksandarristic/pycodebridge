# TASK-0101 — Orchestrator flow: task branch + sequential/parallel dispatch

**Branch:** `feature/dispatch-orchestrator`
**Status:** TODO

## Goal

Implement the core orchestration logic: when a `!c` message contains `@agent` mentions,
create a persistent task branch, run the Claude planning step (if orchestrated), then
dispatch worker agents sequentially or in parallel — each in their own worktree forked
from the task branch.

This wires together the parser (TASK-0099), the worktree service (TASK-0095), and the
existing backend runner. No output formatting in this task (TASK-0102 covers that).

---

## New concepts

### Task branch

A branch that persists across multiple agent invocations for a channel session.
Naming: `task/<repo>/<yyyymmdd-hhmmss>` (created once per `!c` that opens a new task).

Stored in session state as `task_branch: str` (see state changes below).

Worker agent branches fork from the task branch:
`task/<repo>/<timestamp>-<agent>` (e.g. `task/myapp/20260623-1430-codex`)

### Task lifecycle

```
!c @claude plan X, dispatch @codex and @gemini
  1. Create task branch: task/myapp/20260623-1430
  2. Claude runs on task branch worktree → commits plan
  3. Codex forks → task/myapp/20260623-1430-codex, runs, commits
     Gemini forks → task/myapp/20260623-1430-gemini, runs, commits
     (steps 3 parallel)
  4. Worker worktrees removed; worker branches kept
  5. Task branch kept; stored in session state
  6. Output handler (TASK-0102) posts results

!c done  (or !c done --pr / !c done --merge)
  → TASK-0103 handles close
```

---

## Changes

### `codebridge/sessions/state.py`

Add to `SessionState`:
```python
task_branch: str = ""   # current persistent task branch, empty when no active task
```
Wire into `_from_dict` (default `""`) and `_to_dict`.

### `codebridge/sessions/service.py`

Add:
```python
def update_task_branch(self, channel_id: str, session: str, branch: str) -> None: ...
def get_task_branch(self, channel_id: str, session: str) -> str: ...
def clear_task_branch(self, channel_id: str, session: str) -> None: ...
```

### `codebridge/sessions/coordinator.py`

Delegate `update_task_branch`, `get_task_branch`, `clear_task_branch`.

### `codebridge/services/worktree.py`

Extend `WorktreeManager.create()` to accept optional `base_branch: str = ""`:
- When `base_branch` is set, create the new worktree branch forked from `base_branch`
  rather than HEAD.
- `git worktree add -b <new_branch> <path> <base_branch>`

### `codebridge/dispatch/orchestrator.py` (new file)

```python
class OrchestratorError(Exception): ...

class Orchestrator:
    def __init__(self, cfg: Config, router: Router, wt_manager: WorktreeManager,
                 coordinator: SessionCoordinator) -> None: ...

    async def run(
        self,
        spec: DispatchSpec,
        channel_id: str,
        session: str,
        repo_path: str,
        sink: MessageSink,
        thread_id: str = "",
    ) -> None:
        """
        Entry point called by the router when parse_dispatch() returns a spec.

        Flow:
        1. Resolve or create task branch (check session state first)
        2. If spec.is_orchestrated: run Claude planning step on task branch worktree
        3. Build worker list (all agents except claude when orchestrated)
        4. If spec.is_fanout: run workers concurrently (asyncio.gather)
           Else: run workers sequentially
        5. Store task_branch in session state
        6. Hand results to output handler (TASK-0102 — stub for now)
        """
```

### `codebridge/routing/router.py`

In `run_codex` (or a new `run_dispatch` method), after parsing the message:
```python
from ..dispatch.parser import parse_dispatch
from ..dispatch.orchestrator import Orchestrator

spec = parse_dispatch(message)
if spec is not None and self._wt_manager is not None:
    await self._orchestrator.run(spec, channel_id, session, repo_path, sink, thread_id)
    return
# existing solo backend path below
```

Router `__init__` gains optional `orchestrator: Orchestrator | None = None`;
`cmd/bridge.py` constructs it when `cfg.worktrees.enabled` (worktrees required for dispatch).

---

## Tests

**File:** `tests/test_orchestrator_flow.py`

Use fakes: `FakeWorktreeManager`, `FakeBackendRunner`, `FakeSink` (extend from TASK-0098 lifecycle tests).

Cover:
- Solo dispatch (`@codex only`) → single agent run, task branch created
- Orchestrated fan-out (`@claude @codex @gemini`) → claude runs first, then codex+gemini in parallel
- Non-orchestrated fan-out (`@codex @gemini`) → both run in parallel, no planning step
- Existing task branch reused when session state already has one
- `WorktreeManager.create()` called with correct `base_branch` for worker agents
- `OrchestratorError` propagated cleanly when worktree creation fails

---

## Done criteria

- Orchestrated fan-out fires Claude first then workers in parallel
- Non-orchestrated fan-out fires all agents in parallel
- Task branch stored in session state after first dispatch
- Subsequent dispatches in same channel reuse existing task branch
- All tests pass; no existing tests broken
