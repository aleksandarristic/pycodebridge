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

- [TASK-0007] Parametrize TOTP requirements in config for command groups.
  - Completed: 2026-02-24
  - Notes: Added nested `discord.totp` config with `command_groups` toggles for `git`, `gh`, and `high_risk`, preserved backward compatibility with legacy flat keys, and updated routing enforcement, docs, examples, and targeted tests.

- [TASK-0008] Broaden known `!git` command coverage (for example: `add`, `fetch`).
  - Completed: 2026-02-23
  - Notes: Added `add` and `fetch` support to git helpers, updated usage/help/docs, and added targeted tests for new routing plus unknown-subcommand rejection.

- [TASK-0001] Discord threads as isolated session contexts.
  - Completed: 2026-02-23
  - Notes: Finished thread room isolation hardening, legacy thread-key migration for state/runtime/queue, and regressions for thread stop + mention handling in threads.
