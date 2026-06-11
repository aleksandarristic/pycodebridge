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

- [TASK-0092] Assess and implement channel prefix rename from `codex-*` to `code-*`.
  - Viability: **viable with low code risk; Discord side requires manual rename.**
  - Code impact:
    - `DEFAULT_CHANNEL_REGEX = r"^codex-([A-Za-z0-9._-]+)$"` in `config.py:13` is the only hardcoded default.
    - The regex is already user-overridable via `discord.channel_name_regex` in the YAML config, so no deployed instance is forced to use the default.
    - State keys use `channel_id` (a Discord snowflake), not channel name — state survives a channel rename with zero migration.
    - Audit logs and session JSONL embed `repo_channel` (the name) as a label only; no functional dependency on it.
  - Migration path:
    1. Change `DEFAULT_CHANNEL_REGEX` to `r"^code-([A-Za-z0-9._-]+)$"`.
    2. Provide a transitional regex operators can set: `r"^cod(?:ex)?-([A-Za-z0-9._-]+)$"` to accept both prefixes while renaming channels.
    3. Rename channels on the Discord server manually (no bot API for bulk-renaming channels; `PATCH /channels/{id}` renames one at a time — could add an admin command).
    4. Once all channels renamed, switch to the new default or remove the transitional regex.
  - Scope:
    - Change `DEFAULT_CHANNEL_REGEX` and update all references in docs/tests/examples.
    - Update `!c help` and README to reflect the new prefix.
    - Optional: add a one-shot DM admin command `!rename-channels code-` that renames all matching guild channels via Discord API (requires `MANAGE_CHANNELS` permission).
  - Risk: **low** — regex is config-driven; state is ID-keyed; no data migration needed. Main work is coordinating the Discord channel renames in production.
