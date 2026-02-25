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
- `TASK-0014` Make repo bash scripts executable and update `update.sh` to verify (after container startup) that Codex CLI and GitHub CLI are authenticated inside the container, displaying warn-only status (no update failure) with concrete remediation steps when unauthenticated, and add a dry-run mode.
- `TASK-0019` Enforce single-session-per-scope semantics with explicit expiry and stale-session controls.
  - Goal:
    - Keep exactly one active logical session per repo channel scope and one per thread scope.
    - Make expiry/reset behavior predictable for operators.
  - Scope:
    - Session scope model:
      - Enforce one session in a channel scope and one session in each thread scope (no parallel named-session fanout in the same scope).
      - Preserve channel/thread isolation boundaries.
    - Expiry flow:
      - On expired session usage, prompt operator to `continue` previous session or `new` session in current channel/thread scope.
      - Ensure prompt UX is consistent for both channel and thread contexts.
    - Stale session cleanup:
      - Provide/validate command behavior for purging stale sessions.
      - Ensure stale purge aligns with new single-session scope model.
    - Reset semantics:
      - Ensure reset is equivalent to creating a new session context in the current scope (fresh start semantics).
  - Acceptance criteria:
    - A scope (channel or thread) cannot accumulate multiple concurrent logical sessions.
    - Expired-session prompt consistently offers `continue` vs `new` in current scope.
    - Stale-session purge command behavior is documented and test-covered.
    - Reset behavior is test-covered as “start anew in current scope”.
