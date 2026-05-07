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

- [TASK-0020] Add Gemini CLI integration with operator-controlled delegation.
  - Goal: allow work to be delegated to Gemini CLI instead of Codex when requested.
  - Scope:
    - Add configurable Gemini CLI runner/invocation support alongside existing Codex runner path.
    - Add command/config controls to select delegation target per request/session (Codex vs Gemini) with explicit operator intent.
    - Preserve existing auth, sandbox, and transport safety expectations for delegated runs.
    - Ensure logs/audit entries identify which backend handled each run.
    - Document setup, required credentials, and usage examples for Gemini delegation.
  - Acceptance criteria:
    - Operator can run tasks through Gemini CLI without breaking existing Codex flows.
    - Backend selection is explicit and visible in command output/logging.
    - Targeted tests cover routing/runner selection and regression on default Codex behavior.

- [TASK-0006] Web-based/dashboard features (status/admin web surface, browser ops views).
