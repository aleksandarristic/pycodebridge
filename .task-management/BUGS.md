# BUGS

Rules:
- Bugs are tracked as tasks and must use stable IDs in format `TASK-####`.
- IDs are immutable, globally unique across `.task-management/`, and never reused.
- When a bug is scheduled for immediate work, move it to `.task-management/TODO.md` and keep the same ID.
- When a bug is deferred as general work, move it to `.task-management/BACKLOG.md` and keep the same ID.
- When a bug is fixed, remove it from this file and append it to `.task-management/DONE.md`.
- When a bug report is invalid/obsolete, remove it from this file and append it to `.task-management/REMOVED.md` with reason.

## Bug backlog

- [TASK-0010] Discord thread bootstrap message leaks into parent channel on thread creation.
  - Symptom:
    - Creating a Discord thread in a channel (example title: `Tasks`) and sending `Hi` in the new thread causes bridge replies to appear in the parent channel instead of staying isolated to the thread.
    - Observed parent-channel output included the thread title, user text, and Codex bootstrap/prompt messages, for example:
      - `CodeBridge Codex asks: Hi. What do you want to work on in pycodebridge?`
      - `CodeBridge I'll check the task-management files and summarize current tasks ...`
  - Reproduction:
    - In a Discord channel, create a new thread.
    - Name the thread `Tasks`.
    - Send `Hi` as the first message in that thread.
    - Observe that bridge responses are posted in the parent channel feed.
  - Expected:
    - Thread messages and all bridge responses remain scoped to the created thread context only.
    - Parent channel should not receive mirrored bootstrap/session output from thread-local conversation starts.
  - Impact:
    - Breaks channel hygiene by leaking thread-only conversation context into shared parent channel.
    - Risks exposing thread work context to unintended channel participants.
    - Creates confusion about active session location and reply target.
  - Investigation scope:
    - Verify Discord adapter/router reply-target resolution for newly created threads during first-message bootstrap.
    - Check whether session mapping initializes against parent channel ID before thread ID is finalized.
    - Add/expand targeted tests for first-message routing behavior in newly created Discord threads.
  - Acceptance criteria:
    - For newly created threads, first and subsequent bridge replies are always posted to that thread, never the parent channel.
    - Add regression coverage for the thread-creation + first-message path (`Hi`) to prevent reintroduction.

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
