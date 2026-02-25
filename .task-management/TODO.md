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
- `TASK-0018` Consolidate state architecture: inventory and eliminate leaky/ad-hoc state persistence points, centralize state reads/writes behind clear service boundaries, and define cleanup lifecycle for stale state artifacts with regression coverage for behavior changes.
  - Scope:
    - Inventory all current state persistence locations/files and classify ownership, purpose, and lifecycle.
    - Remove or migrate ad-hoc state writes into a centralized state service boundary.
    - Standardize state mutation flow to reduce partial updates and drift between in-memory/runtime and persisted state.
    - Define and implement stale state cleanup rules (for example: abandoned session artifacts, expired conflict markers, obsolete temp state).
    - Document the state model and mutation entry points for operators and maintainers.
  - Acceptance criteria:
    - Single documented source of truth for each persisted state domain (sessions, routing/conflict metadata, runtime coordination markers).
    - No known state writes bypass centralized state service APIs in changed areas.
    - Cleanup behavior for stale state artifacts is implemented, deterministic, and tested.
    - Regression tests cover at least one previously leaky/ad-hoc state flow that is now consolidated.
