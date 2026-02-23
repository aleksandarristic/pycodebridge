# TODO (Immediate)

Rules:
- Use stable task IDs in format `TASK-####`.
- IDs are immutable and never reused.
- Tasks promoted from `.task-management/BUGS.md` keep the same ID.
- When moving a task to backlog, keep the same ID.
- When completing a task, remove it from this file and append it to `.task-management/DONE.md`.
- When dropping a task, remove it from this file and append it to `.task-management/REMOVED.md`.

## Active tasks

- [TASK-0001] Discord threads as isolated session contexts (immediate).
  - Goal: allow each Discord thread under `#codex-<repo>` to act as an independent session workspace with first-class Discord UI.
  - Scope:
    - Resolve repo from parent mapped channel when message originates in a thread.
    - Treat each thread as an isolated room key (`discord:<channel_id>:<thread_id>`).
    - Keep session namespace, queue, sticky selection, and run control isolated per thread room.
    - Preserve existing behavior for non-thread channel messages.
  - Acceptance criteria:
    - `!c start` in parent channel and in multiple threads can run concurrently for the same repo.
    - Output and follow-up commands stay scoped to the originating thread.
    - Commands in one thread do not affect sessions in sibling threads.
    - Existing channel-only workflows remain backward compatible.
    - Add targeted integration tests covering thread isolation and parent-channel compatibility.
