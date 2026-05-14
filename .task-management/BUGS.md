# BUGS

Rules:
- Bugs are tracked as tasks and must use stable IDs in format `TASK-####`.
- IDs are immutable, globally unique across `.task-management/`, and never reused.
- When a bug is scheduled for immediate work, move it to `.task-management/TODO.md` and keep the same ID.
- When a bug is deferred as general work, move it to `.task-management/BACKLOG.md` and keep the same ID.
- When a bug is fixed, remove it from this file and append it to `.task-management/DONE.md`.
- When a bug report is invalid/obsolete, remove it from this file and append it to `.task-management/REMOVED.md` with reason.

## Bug backlog

- [TASK-0057] [Low] Single-token input to `parse_session_and_prompt` always treated as session name.
  - `commands/parse.py` — `!c run hello` treats `hello` as a session name and produces an empty prompt, resulting in an error or empty Codex invocation. New users trying short prompts will always hit this.
  - Fix: if the token does not match a known session name, treat it as the start of the prompt.
