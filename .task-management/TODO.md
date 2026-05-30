# TODO (Immediate)

Rules:
- Use stable task IDs in format `TASK-####`.
- IDs are immutable and never reused.
- Tasks promoted from `.task-management/BUGS.md` keep the same ID.
- When moving a task to backlog, keep the same ID.
- When completing a task, remove it from this file and append it to `.task-management/DONE.md`.
- When dropping a task, remove it from this file and append it to `.task-management/REMOVED.md`.

## Active tasks

- [TASK-0066] Track cached input tokens and verify/fix per-event usage summation.
  - Context: `usage_from_event` (`routing/helpers.py:113`) reads only `input_tokens`/`output_tokens`/`total_tokens` and discards `cached_input_tokens`. `update_usage` (`router.py:3272`) **sums** usage from every JSONL event; if Codex reports cumulative running totals within a single `exec` run, session/budget totals are over-counted.
  - Goal: account for cached tokens and ensure run/session usage is counted correctly (incremental, not double-counted).
  - Scope:
    - Confirm the real `codex exec --json` usage event shape (incremental vs cumulative; field names for cached tokens) against live output, and record the finding in the ticket/commit.
    - Capture `cached_input_tokens` (and `cachedInputTokens`) in `UsageStats`; surface it in `!c stats` and the run-completion summary.
    - If usage is cumulative, fix `update_usage` to store the latest totals (or compute deltas) instead of summing.
  - Acceptance criteria:
    - Usage totals match Codex's reported totals for a multi-event run (no over-count).
    - Cached tokens are tracked and visible in stats/summary output.
    - Tests cover the corrected accounting and cached-token parsing; existing usage/budget tests pass.
  - Depends-on for policy: see [TASK-0068] for whether budgets discount cached tokens.
