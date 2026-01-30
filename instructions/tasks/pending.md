# Pending Tasks

## TOC
- 68) TODO - Parse and format Codex `/status` output (issue plan)
- 69) TODO - Integrate parsed `/status` into `!c status` (issue plan)
- 70) TODO - Add best-effort usage snapshot on quit/stop/kill (issue plan)
- 63) TODO - Unify command parsing utilities (issue plan)
- 64) TODO - Formalize session lifecycle invariants (issue plan)

---

68) TODO - Parse and format Codex `/status` output (issue plan)
- Owner: TBD
- Complexity: High
- Depends on: 67
- Subtasks:
  - Parse Codex `/status` output into a structured summary (tolerate format drift).
  - Format a chat-friendly summary (context window, token usage, 5h limit, weekly limit, current directory, and other key fields present).
  - Add unit tests for parsing and formatting.

69) TODO - Integrate parsed `/status` into `!c status` (issue plan)
- Owner: TBD
- Complexity: Medium
- Depends on: 68
- Subtasks:
  - Extend `!c status` output to include parsed `/status` summary.
  - Ensure the output remains concise and stable across platforms.
  - Add tests for `!c status` formatting.

70) TODO - Add best-effort usage snapshot on quit/stop/kill (issue plan)
- Owner: TBD
- Complexity: Medium
- Depends on: 68
- Subtasks:
  - Reuse `/status` parsing to attach a best-effort usage snapshot to explicit end commands (`!c quit/stop/kill`).
  - Skip aggregation across sessions; report only the session being ended.
  - Add tests for end-command usage snapshot behavior.

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
