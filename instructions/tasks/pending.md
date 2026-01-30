# Pending Tasks

## TOC
- 56) TODO - Router surface cleanup (issue plan)
- 57) TODO - Standardize command routing utilities (issue plan)
- 60) TODO - Clarify adapter contract usage (issue plan)
- 61) TODO - Extend `!c status` with Codex `/status` details (issue plan)

---

56) TODO - Router surface cleanup (issue plan)
- Owner: TBD
- Subtasks:
  - Identify Router methods that can move into `handlers/*` or small service helpers.
  - Extract at least one low-risk block (status formatting or reply helpers) into a dedicated module.
  - Add/update unit tests covering the moved behavior.

57) TODO - Standardize command routing utilities (issue plan)
- Owner: TBD
- Subtasks:
  - Audit duplicated parsing/validation logic across handlers.
  - Add shared helpers in `command_parse.py` or `command_registry.py`.
  - Update handlers to use shared utilities and add regression tests.

60) TODO - Clarify adapter contract usage (issue plan)
- Owner: TBD
- Subtasks:
  - Identify adapter-specific conditionals in Router and handlers.
  - Prefer capabilities checks or adapter-layer behavior where possible.
  - Add tests covering any adjusted routing behavior.

61) TODO - Extend `!c status` with Codex `/status` details (issue plan)
 - Owner: TBD
- Subtasks:
  - Extend `!c status` output to include parsed information from Codex `/status` output (as currently reported by Codex), e.g. context window + token usage, 5h limit, weekly limit, current directory, and any other key fields present.
  - Implement `/status` retrieval by issuing the Codex `/status` command and parsing the response into a stable, chat-friendly summary (tolerate format drift).
  - This must be an immediate command: it can run even when other jobs are already running (do not queue behind the per-channel job queue).
  - Ensure it does not mutate session state (thread id/model) and does not interfere with the currently running job.
  - Add unit tests for parsing and for the "immediate while running" behavior using fakes/mocks.
