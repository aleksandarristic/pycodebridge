# Pending Tasks

## TOC
- 70) TODO - Add best-effort usage snapshot on quit/stop/kill (issue plan)
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
