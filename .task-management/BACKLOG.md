# BACKLOG

Rules:
- Use stable task IDs in format `TASK-####`.
- IDs are immutable and never reused.
- Bugs moved from `.task-management/BUGS.md` keep the same ID.
- When promoting a task to immediate TODO, move the task block to `.task-management/TODO.md` and keep the same ID.
- When completing a task, remove it from this file and append it to `.task-management/DONE.md`.
- When dropping a task, remove it from this file and append it to `.task-management/REMOVED.md`.

## Backlog tasks

- [TASK-0004] Role-based permissions model (Discord-role driven access tiers).

- [TASK-0020] Add Gemini CLI integration with operator-controlled delegation.
  - Goal: allow work to be delegated to Gemini CLI instead of Codex when requested.
  - Scope:
    - Implement as a `GeminiBackend` on the agent abstraction (TASK-0069) and reuse the per-session selection from TASK-0070 rather than building a parallel runner path.
    - Map Gemini CLI invocation/stream output into `AgentBackend.build_*` and `parse()` (`NormalizedEvent`).
    - Preserve existing auth, sandbox, and transport safety expectations for delegated runs.
    - Ensure logs/audit entries identify which backend handled each run.
    - Document setup, required credentials, and usage examples for Gemini delegation.
  - Acceptance criteria:
    - Operator can run tasks through Gemini CLI without breaking existing Codex flows.
    - Backend selection is explicit and visible in command output/logging.
    - Targeted tests cover routing/runner selection and regression on default Codex behavior.
  - Depends on: TASK-0069 (agent abstraction), TASK-0070 (per-session selection).


- [TASK-0006] Web-based/dashboard features (status/admin web surface, browser ops views).

- [TASK-0066] Track cached input tokens and verify/fix per-event usage summation.
  - Context: `usage_from_event` (`routing/helpers.py:113`) reads only `input_tokens`/`output_tokens`/`total_tokens` and discards `cached_input_tokens`. `update_usage` (`router.py:3272`) **sums** usage from every JSONL event; if Codex reports cumulative running totals within a single `exec` run, session/budget totals are over-counted.
  - Goal: account for cached tokens and ensure run/session usage is counted correctly (incremental, not double-counted).
  - Scope:
    - Confirm the real `codex exec --json` usage event shape (incremental vs cumulative; field names for cached tokens) against live output, and record the finding in the ticket/commit. (Captured logs at `/Users/leka/Code/_bridge/logs` only contained `thread.started`/`turn.started`/`item.completed` with no usage event, so the shape still needs a live sample.)
    - Capture `cached_input_tokens` (and `cachedInputTokens`) in `UsageStats`; surface it in `!c stats` and the run-completion summary.
    - If usage is cumulative, fix `update_usage` to store the latest totals (or compute deltas) instead of summing.
  - Acceptance criteria:
    - Usage totals match Codex's reported totals for a multi-event run (no over-count).
    - Cached tokens are tracked and visible in stats/summary output.
    - Tests cover the corrected accounting and cached-token parsing; existing usage/budget tests pass.
  - Blocked-on: a real `codex exec --json` usage line (field names + cumulative-vs-incremental) before the summation fix can be implemented safely. Moved to backlog 2026-05-30 pending that sample.
