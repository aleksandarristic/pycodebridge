# TASK-0124 — DM assistant: session control commands

**Status:** DONE

## Intent

Make existing session control commands work for the assistant session
in DM context (no bound repo).

## Scope

- The following commands should operate on the `"dm"` session when
  issued in DM with no bound repo:
  - `!c agent [codex|claude|gemini] [model] [effort]` — switch backend
  - `!c model <id|default>` / `!c effort <level|default>` — set model/effort
  - `!c status` / `!c stats` / `!c peek` — show assistant session state
  - `!c stop` / `!c interrupt` / `!c kill` — run control
  - `!c reset` — clear assistant session
  - `!c choose continue|new|compact` — resolve conflict prompt
  - `!c logs [n]` — show recent assistant session log
- In DM context the `session` argument to these commands defaults to
  `"dm"` when no repo is bound (rather than `"default"`).
- `!c agent` / `!c model` / `!c effort` with no args show current
  assistant backend/model/effort.
- `!c agents` / `!c models` / `!c efforts` remain open (no TOTP).
- No new command names — only context-sensitive routing of existing ones.
- Update DM help text to mention assistant session commands.
- Add tests for command routing in no-bound-repo DM context.

## Acceptance Criteria

- `!c agent claude` in DM (no bound repo) switches the assistant backend.
- `!c status` reflects the assistant session state.
- `!c reset` clears the assistant session without affecting bound-repo
  sessions.
