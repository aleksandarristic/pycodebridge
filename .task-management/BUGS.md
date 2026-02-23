# BUGS

Rules:
- Bugs are tracked as tasks and must use stable IDs in format `TASK-####`.
- IDs are immutable, globally unique across `.task-management/`, and never reused.
- When a bug is scheduled for immediate work, move it to `.task-management/TODO.md` and keep the same ID.
- When a bug is deferred as general work, move it to `.task-management/BACKLOG.md` and keep the same ID.
- When a bug is fixed, remove it from this file and append it to `.task-management/DONE.md`.
- When a bug report is invalid/obsolete, remove it from this file and append it to `.task-management/REMOVED.md` with reason.

## Bug backlog

- [TASK-0009] Intermittent `!reset` top-level alias is not parsed as `!c reset`.
  - Symptom:
    - In session/chatroom usage, sending `!reset` sometimes does not execute the expected reset flow (`!c reset` equivalent).
  - Impact:
    - Operators cannot reliably recover session state using the documented top-level command pattern.
    - Inconsistent command UX across rooms/contexts increases risk of stuck or stale sessions.
  - Investigation scope:
    - Reevaluate top-level command parsing and alias normalization in mapped repo channels/threads/chatrooms.
    - Validate behavior parity between prefixed commands (`!c reset`) and top-level shortcuts (`!reset`) across:
      - parent channels
      - Discord threads
      - active-session chat relay paths
    - Confirm command parsing order does not incorrectly route `!reset` into plain prompt/session input handling.
  - Acceptance criteria:
    - `!reset` is parsed and handled identically to `!c reset` in supported channel/thread contexts.
    - Behavior is deterministic (no intermittent parse misses across repeated runs).
    - Add targeted integration tests for top-level `!reset` parsing in parent channel + thread/session contexts.
