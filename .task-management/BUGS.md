# BUGS

Rules:
- Bugs are tracked as tasks and must use stable IDs in format `TASK-####`.
- IDs are immutable, globally unique across `.task-management/`, and never reused.
- When a bug is scheduled for immediate work, move it to `.task-management/TODO.md` and keep the same ID.
- When a bug is deferred as general work, move it to `.task-management/BACKLOG.md` and keep the same ID.
- When a bug is fixed, remove it from this file and append it to `.task-management/DONE.md`.
- When a bug report is invalid/obsolete, remove it from this file and append it to `.task-management/REMOVED.md` with reason.

## Bug backlog

- [TASK-0072] `!reset`/`!c reset` raises `TypeError` when a session has an active process.
  - Symptom: resetting a session that has a running process crashes the handler with `TypeError: object NoneType can't be used in 'await' expression`.
  - Cause: `router.py:1656` calls `await proc.kill()`, but `Process.kill` (`codebridge/agents/base.py`) is synchronous and returns `None`, so awaiting it raises. The sibling stop path at `router.py:1610` correctly calls `proc.kill()` without `await`.
  - Repro: exercised by 3 currently-failing tests in `tests/test_integration_harness.py`: `test_integration_reset_session_clears_context_and_allows_fresh_start`, `test_integration_bang_reset_alias_clears_context_and_allows_fresh_start`, `test_integration_bang_reset_alias_works_in_discord_thread_scope`.
  - Fix: drop the `await` at `router.py:1656` (`proc.kill()`); `Process.kill` is intentionally synchronous (only `stop`/`write`/`wait` are async).
  - Notes: pre-existing on HEAD; predates TASK-0069 (the line was moved verbatim into `agents/base.py` but the bug is in the router call site). Acceptance: the 3 tests pass and no behavior change elsewhere.

