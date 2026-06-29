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

- [TASK-0130] Detect auto-compaction and signal it to the Discord user.
  - Context: Both the Claude Code CLI (`claude -p --output-format stream-json`) and Codex CLI (`codex exec --json`) can auto-compact the conversation context when it approaches the context window limit. The bridge currently does not detect or surface this event, leaving the user unaware that their session history was summarised and truncated.
  - Goal: When auto-compaction fires (for either backend), send a brief status message to the Discord channel notifying the user that context was compacted and the session continues.
  - Scope:
    - **Claude backend:** Identify the stream-json event emitted on auto-compact (likely a `system` event with a `subtype` like `compact` or `auto_compact`). Add a case to `ClaudeBackend.parse` in `codebridge/agents/claude.py` to emit a `NormalizedEvent` with `type="compact"` (or similar).
    - **Codex backend:** Identify the equivalent JSONL event shape from `codex exec --json`. Add handling in `CodexBackend.parse` in `codebridge/codex.py` if Codex emits such an event.
    - **Router:** In `run_codex` (`codebridge/routing/router.py`), detect `type=="compact"` events in the `on_jsonl` callback and relay a user-visible status message (e.g. `"[session] Context was auto-compacted — session continues."`) via the sink.
    - Keep the message short and clearly non-alarming; do not interrupt or block the run.
  - Acceptance criteria:
    - A Discord message is sent when auto-compaction occurs for both Claude and Codex backends.
    - The bridge continues the run normally after signalling.
    - Unit tests cover compact-event detection and relay for both backends.
  - Note: The exact event shape for auto-compact needs to be confirmed from live logs or CLI documentation before implementation.
