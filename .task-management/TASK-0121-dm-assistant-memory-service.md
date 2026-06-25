# TASK-0121 — DM assistant: per-user memory service

## Intent

Persist a per-user markdown memory file so the assistant retains
knowledge across sessions (user preferences, notes, past context).

## Scope

- Add `DmMemoryService` in `codebridge/services/dm_memory.py`:
  - `memory_dir` resolved from config (`dm_assistant.memory_dir` or
    `{state.data_dir}/dm-memory/`).
  - `get_path(user_id: str) -> Path` — returns the per-user file path.
  - `read(user_id: str) -> str` — returns file content or `""` if absent.
  - `exists(user_id: str) -> bool`.
- Memory files are plain markdown, written and maintained by the agent
  itself via normal file tools during a session.
- Service is instantiated in `Router.__init__` alongside other services
  (health, file transfers, git bootstrap).
- Wire into `Router` as `self.dm_memory`.
- Add unit tests for path resolution and read fallback.

## Acceptance Criteria

- `read()` returns `""` for a missing file without raising.
- Path is stable per `user_id` across restarts.
- Service is accessible from the router for use in TASK-0122.
