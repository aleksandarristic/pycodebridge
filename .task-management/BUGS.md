# BUGS

Rules:
- Bugs are tracked as tasks and must use stable IDs in format `TASK-####`.
- IDs are immutable, globally unique across `.task-management/`, and never reused.
- When a bug is scheduled for immediate work, move it to `.task-management/TODO.md` and keep the same ID.
- When a bug is deferred as general work, move it to `.task-management/BACKLOG.md` and keep the same ID.
- When a bug is fixed, remove it from this file and append it to `.task-management/DONE.md`.
- When a bug report is invalid/obsolete, remove it from this file and append it to `.task-management/REMOVED.md` with reason.

## Bug backlog

- [TASK-0084] Main conversation session hangs while heartbeat continues.
  - Symptom: session stops responding to user input but heartbeat pings continue every 2m
  - Observed in: default session with claude backend
  - Context: occurred while a thread conversation (separate session) was running normally
  - Impact: user cannot stop or interact with hung session; must manually manage
  - Root cause unknown: investigate whether heartbeat task holds a lock, or if session._run_heartbeat is decoupled from session.run_codex lifecycle

- [TASK-0085] Wrong backend error on stop command after backend switch.
  - Symptom: `!esc` / `!stop` / `!c /quit` returns "no codex running" error even when claude is the active backend
  - Reproduction: (1) start agent in thread with codex backend, (2) switch main session backend to claude via `!c agent`, (3) attempt stop/quit — error reports codex as missing
  - Root cause: stop/quit handlers (`_cmd_esc`, `_cmd_stop`, `_cmd_quit` or similar) appear to cache the *initial* backend choice or read backend from wrong scope instead of current session state
  - Fix needed: ensure stop commands read the *current* session backend before error-checking or dispatching to kill handlers
