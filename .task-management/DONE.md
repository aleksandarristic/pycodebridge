# DONE

Rules:
- Keep original task ID when moving entries here.
- Keep entries in reverse chronological order (newest first).
- Include completion date and optional notes.

Format:
- [TASK-0000] Short task title.
  - Completed: YYYY-MM-DD
  - Notes: Optional

## Completed tasks

- [TASK-0017] Consolidate logging architecture with unified session JSONL streams and archival rotation.
  - Completed: 2026-02-25
  - Notes: Added consolidated per-session JSONL logs under `state.log_dir/session_jsonl/active/<channel>/<session>.jsonl`, wired key run/codex/output/error events, implemented mandatory `.tgz` archival for active logs older than 30 days into `session_jsonl/archive/...`, retained archives indefinitely, and updated tests/docs.

- [TASK-0016] Add top-level `!branch` command for branch + clean-state visibility.
  - Completed: 2026-02-24
  - Notes: Added a read-only `branch` command (`!c branch` and `!branch`) that summarizes current branch and working tree clean/not-clean status via git helper output, with targeted tests and docs updates.

- [TASK-0015] Universal channel/thread top-level `!<command>` support and stop/interrupt shortcut semantics.
  - Completed: 2026-02-24
  - Notes: Added generic top-level dispatch for all registered channel command names/aliases (`!command`/`!alias`), mapped `!stop` to `stop` (ESC then SIGINT), updated `interrupt` to ESC-only with aliases `int/esc/escape`, and added/updated targeted routing + help/model command tests and docs.

- [TASK-0011] Discord-only transport surface; remove Telegram/Slack wiring while preserving modular transport architecture.
  - Completed: 2026-02-24
  - Notes: Removed Telegram/Slack adapters and runtime wiring, deleted Telegram/Slack docs, simplified config validation to Discord-only transport, updated examples/architecture/testing docs, and adjusted targeted tests accordingly.

- [TASK-0007] Parametrize TOTP requirements in config for command groups.
  - Completed: 2026-02-24
  - Notes: Added nested `discord.totp` config with `command_groups` toggles for `git`, `gh`, and `high_risk`, preserved backward compatibility with legacy flat keys, and updated routing enforcement, docs, examples, and targeted tests.

- [TASK-0008] Broaden known `!git` command coverage (for example: `add`, `fetch`).
  - Completed: 2026-02-23
  - Notes: Added `add` and `fetch` support to git helpers, updated usage/help/docs, and added targeted tests for new routing plus unknown-subcommand rejection.

- [TASK-0001] Discord threads as isolated session contexts.
  - Completed: 2026-02-23
  - Notes: Finished thread room isolation hardening, legacy thread-key migration for state/runtime/queue, and regressions for thread stop + mention handling in threads.
