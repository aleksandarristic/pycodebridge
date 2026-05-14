# REMOVED

Rules:
- Keep original task ID when moving entries here.
- Keep entries in reverse chronological order (newest first).
- Include removal date and reason.

Format:
- [TASK-0000] Short task title.
  - Removed: YYYY-MM-DD
  - Reason: Why it was removed or cancelled.

## Removed tasks

- [TASK-0047] Wrong Discord attribute used for thread detection in sink routing.
  - Removed: 2026-05-14
  - Reason: Not a real bug. `message.thread` is the thread created by a starter message; routing replies there is intentional and tested. `message.channel` is already a thread object for in-thread messages, so both paths are correct.

