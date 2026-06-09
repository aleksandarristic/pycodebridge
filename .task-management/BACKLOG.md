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

- [TASK-0075] Require TOTP for DM reset-all.
  - Context: DM `reset all` can clear stored context, cancel queued jobs, and stop active work across channels with only admin allowlist plus yes/no confirmation.
  - Goal: treat reset-all as a high-risk operation when TOTP is enabled.
  - Scope:
    - Add DM reset-all to the high-risk TOTP-gated admin command set.
    - Preserve the existing second-step yes/no confirmation.
    - Keep non-admin rejection behavior unchanged.
  - Acceptance criteria:
    - With TOTP enabled, DM reset-all requires a valid TOTP before the confirmation prompt.
    - Tests cover missing TOTP, valid TOTP plus yes, confirmation cancel, and non-admin rejection.

- [TASK-0076] Harden upload persistence against aggregate-size abuse and symlink races.
  - Context: upload checks are per attachment only, and validated destination paths are later passed to `Attachment.save()` without final no-symlink/exclusive write checks.
  - Goal: make uploads bounded and safe even when repo contents change concurrently.
  - Scope:
    - Add aggregate upload size and attachment-count limits.
    - Save to a safe temporary file under the repo, then finalize with containment and symlink checks.
    - Avoid following final-path symlinks and avoid overwriting outside-repo targets.
  - Acceptance criteria:
    - Tests cover aggregate-size rejection, too-many-attachments rejection, path traversal, existing symlinks, and race-resistant finalization.
    - Existing upload/download tests pass.

- [TASK-0077] Make model and effort default clearing explicit.
  - Context: `!effort default` and optional `!model ... default` normalize to an empty string, but session state only updates model/reasoning when a non-empty value is supplied, so existing overrides are not cleared.
  - Goal: make user-visible "default" behavior actually remove session overrides.
  - Scope:
    - Add an explicit clear-override path for model and reasoning effort.
    - Decide command UX for clearing only effort vs clearing model and effort together.
    - Preserve backend-specific effort validation.
  - Acceptance criteria:
    - `!effort default` clears a stored effort override.
    - `!model <id> default` clears stored effort while applying the model, or errors with clear guidance if that UX is rejected.
    - Tests cover Codex and Claude sessions.

- [TASK-0078] Rework limited helper subprocess output draining.
  - Context: `run_limited_command()` stops reading once the output cap is exceeded, then waits for process exit; noisy commands can block on full pipes and be killed by timeout.
  - Goal: cap retained output without blocking successful large-output commands.
  - Scope:
    - Continue draining stdout/stderr after retained output reaches the cap.
    - Wait for process completion and reader tasks together under one timeout.
    - Return a clear truncation marker in helper replies.
  - Acceptance criteria:
    - A helper command that writes more than `HELPER_OUTPUT_LIMIT` and exits normally does not time out.
    - Tests cover large stdout, large stderr, timeout, and non-zero exit.

- [TASK-0079] Guard public health endpoint binds.
  - Context: port-only health binds default to loopback, but explicit non-loopback binds expose unauthenticated operational counts and recent error timestamps.
  - Goal: avoid accidental unauthenticated health exposure on public interfaces.
  - Scope:
    - Reject or warn on non-loopback binds unless an explicit config flag or token is set.
    - Document intended local-only and public-bind deployment modes.
    - Add tests for loopback, non-loopback rejected/allowed, and optional token behavior if implemented.
  - Acceptance criteria:
    - Default health configuration remains local-only.
    - Non-loopback exposure requires explicit operator intent.
