# Pending Tasks

## TOC
- 70) TODO - Add best-effort usage snapshot on quit/stop/kill (issue plan)
- 71) TODO - Make `!c status` consistently show parsed Codex `/status` block (issue plan)
- 63) TODO - Unify command parsing utilities (issue plan)
- 64) TODO - Formalize session lifecycle invariants (issue plan)

---

70) TODO - Add best-effort usage snapshot on quit/stop/kill (issue plan)
- Owner: TBD
- Complexity: Medium
- Depends on: 68
- Subtasks:
  - Reuse `/status` parsing to attach a best-effort usage snapshot to explicit end commands (`!c quit/stop/kill`).
  - Skip aggregation across sessions; report only the session being ended.
  - Add tests for end-command usage snapshot behavior.

71) TODO - Make `!c status` consistently show parsed Codex `/status` block (issue plan)
- Owner: TBD
- Complexity: High
- Depends on: 67, 68, 69
- Subtasks:
  - Desired: `!c status` should append a “Codex /status” block containing model, directory, context window, and limits whenever a session exists, regardless of active/idle state.
  - Actual: `!c status` only shows the repo/session list; the `/status` block is absent even after multiple tries, despite the immediate `/status` helper and parser updates.
  - Suspected causes to investigate: `/status` output emitted outside `on_output`/`on_jsonl` callbacks; output format differs from parser assumptions; immediate run not attached to the correct session/thread; or the Codex CLI discards `/status` output when invoked in non-interactive `exec --json` mode.
  - Add temporary debug logging to capture raw `/status` lines and callback paths to identify where output is lost; remove logs once fixed.
  - Update parser/runner as needed so the block appears reliably in Discord.
  - Add regression tests that simulate the observed output format (including cases where `/status` yields no `display_texts`).

63) TODO - Unify command parsing utilities (issue plan)
- Owner: TBD
- Complexity: Medium
- Subtasks:
  - Centralize duplicated parsing/validation in `command_parse.py`.
  - Replace ad-hoc handler parsing in `command_registry.py` with shared helpers.
  - Add regression tests for session parsing, limits, and error handling.

64) TODO - Formalize session lifecycle invariants (issue plan)
- Owner: TBD
- Complexity: High
- Subtasks:
  - Define explicit lifecycle methods in `SessionService` for start/resume/stop/model changes.
  - Move state mutation logic from Router/handlers into the service.
  - Add tests covering lifecycle invariants and active process transitions.
