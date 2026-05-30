# REMOVED

Rules:
- Keep original task ID when moving entries here.
- Keep entries in reverse chronological order (newest first).
- Include removal date and reason.

Format:
- [TASK-0000] Short task title.
  - Removed: YYYY-MM-DD
  - Reason: Why it was removed or cancelled.

## Removed tasks

- [TASK-0068] Decide budget pricing policy for cached input tokens.
  - Removed: 2026-05-30
  - Reason: Dropped at user request. Was a downstream product decision dependent on TASK-0066 (cached-token tracking), which is itself backlogged pending a real Codex usage sample. Can be re-raised if/when budgets need to weight cached tokens differently from fresh input.

- [TASK-0056] `on_jsonl` lambda in `run_codex` closes over `sink` by reference.
  - Removed: 2026-05-14
  - Reason: Not actionable. `sink` is a local function parameter in `run_codex` that is never reassigned, so the lambda captures a stable value, not a mutable reference.

- [TASK-0048] `_discord_repo_channel_is_private()` fails open on all error paths.
  - Removed: 2026-05-14
  - Reason: Inverted logic in review. Returning `False` causes the caller to skip the message (not process it), which is fail-safe, not fail-open.

- [TASK-0045] TOCTOU race in `_next_seq()` causes silent audit log data loss.
  - Removed: 2026-05-14
  - Reason: Not a real race. `_next_seq()` is synchronous with no await points; in a single-threaded asyncio event loop two coroutines cannot interleave within it.

- [TASK-0047] Wrong Discord attribute used for thread detection in sink routing.
  - Removed: 2026-05-14
  - Reason: Not a real bug. `message.thread` is the thread created by a starter message; routing replies there is intentional and tested. `message.channel` is already a thread object for in-thread messages, so both paths are correct.

