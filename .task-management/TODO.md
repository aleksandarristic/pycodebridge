# TODO (Immediate)

Rules:
- Use stable task IDs in format `TASK-####`.
- IDs are immutable and never reused.
- Tasks promoted from `.task-management/BUGS.md` keep the same ID.
- When moving a task to backlog, keep the same ID.
- When completing a task, remove it from this file and append it to `.task-management/DONE.md`.
- When dropping a task, remove it from this file and append it to `.task-management/REMOVED.md`.

## Active tasks
- `TASK-0012` Remove compat retry fallback in router; execute Codex only with original args and fail fast on non-zero exit without argument mutation/retry.
- `TASK-0013` Add comprehensive Codex CLI argument-ordering tests that assert bridge arg-building contract (presence and relative order of required flags/arguments across start/resume variants and supported order permutations).
