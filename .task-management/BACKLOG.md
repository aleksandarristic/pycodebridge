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

- [TASK-0061] Remove orphaned `session_expired` conflict handling in `handle_choose`.
  - Goal: drop unreachable code after expired sessions switched to auto-start (42e73ff).
  - Scope:
    - Remove/simplify the `conflict.reason == "session_expired"` branch in `codebridge/handlers/core.py` (~line 346); no flow creates that reason anymore.
    - Confirm no remaining producers of `PendingConflict(reason="session_expired")` and update/remove related tests.
  - Acceptance criteria:
    - No references to `session_expired` remain except intentional ones; changed-area tests pass.

- [TASK-0062] Reconcile the `compact` option with the start-conflict prompt.
  - Goal: make `choose compact` discoverable, or remove the shortcut if compaction is no longer an offered path.
  - Scope:
    - Decide whether the start-conflict message should advertise `!compact` alongside `!cont`/`!new`.
    - If kept, ensure compact-from-start-conflict produces a sensible prompt (start conflicts carry no `prompt`, so the "new request" is currently empty).
  - Acceptance criteria:
    - The compact shortcut is either surfaced consistently or intentionally retired, with tests reflecting the decision.

- [TASK-0063] Decide expired-session recovery policy (auto-new vs preserve context).
  - Goal: confirm whether unconditionally discarding the prior thread on expiry is desired, or whether expired auto-start should compact prior context and/or be configurable.
  - Scope:
    - Evaluate preserving the old "compact on expiry" behavior (summarize prior thread into the new prompt) vs. current blank start.
    - Consider a config toggle (for example `session_idle_ttl` action: `new` | `compact` | `prompt`).
  - Acceptance criteria:
    - Documented decision; if a behavior/config change is chosen, implement with targeted tests.

