# Removed Tasks

## TOC
- 34) REMOVED - Discord threads-only adapter variant (issue plan)

---

34) REMOVED - Discord threads-only adapter variant (issue plan)
- Owner: TBD
- Subtasks:
  - Add config flag for threads-only mode and document in `DISCORD.md`/`README.md`.
  - Implement thread creation/selection on first message; persist thread id per session.
  - Route responses to thread sink; ensure uploads/downloads work in threads.
  - Add adapter tests covering thread routing + session mapping.
