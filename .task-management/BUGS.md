# BUGS

Rules:
- Bugs are tracked as tasks and must use stable IDs in format `TASK-####`.
- IDs are immutable, globally unique across `.task-management/`, and never reused.
- When a bug is scheduled for immediate work, move it to `.task-management/TODO.md` and keep the same ID.
- When a bug is deferred as general work, move it to `.task-management/BACKLOG.md` and keep the same ID.
- When a bug is fixed, remove it from this file and append it to `.task-management/DONE.md`.
- When a bug report is invalid/obsolete, remove it from this file and append it to `.task-management/REMOVED.md` with reason.

## Bug backlog

- [TASK-0082] Revisit Gemini backend because Gemini is not working.
  - Context: The Gemini backend was added, but Gemini is currently not working end to end.
  - Goal: revalidate the Gemini CLI invocation, stream-json schema, auth/env assumptions, resume behavior, and parser against the current Gemini CLI.
  - Scope:
    - Reproduce the failure with a real Gemini CLI run and capture stdout/stderr plus exit code.
    - Verify command arguments for start, resume by id, resume latest, model selection, approval mode, and trust/workspace flags.
    - Update `GeminiBackend` parsing and runner integration to match the current CLI behavior.
    - Refresh `.task-management/TASK-0020-gemini-stream-json-schema.md` if the schema has changed.
  - Acceptance criteria:
    - Gemini start and resume paths work against a real configured Gemini CLI.
    - User-visible Gemini errors are relayed clearly instead of appearing as silent failures.
    - Tests cover the captured real failure shape and successful parser/argument paths.
