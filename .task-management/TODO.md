# TODO (Immediate)

Rules:
- Use stable task IDs in format `TASK-####`.
- IDs are immutable and never reused.
- Tasks promoted from `.task-management/BUGS.md` keep the same ID.
- When moving a task to backlog, keep the same ID.
- When completing a task, remove it from this file and append it to `.task-management/DONE.md`.
- When dropping a task, remove it from this file and append it to `.task-management/REMOVED.md`.

## Active tasks

### Repo bootstrap improvements

- TASK-0112 — Update AGENTS.sample.md with dispatch workflow section; wire it into docker config
- TASK-0113 — `!c gh-create` command: check existing GH repo, create if absent, add remote

### Repo file transfer UX

- TASK-0117 — Verify and document repo file download request workflow

### DM assistant

- TASK-0120 — DM assistant: config section (`dm_assistant.*`)
- TASK-0121 — DM assistant: per-user memory service
- TASK-0122 — DM assistant: start prompt builder (repo list, session summary, memory)
- TASK-0123 — DM assistant: routing and session lifecycle
- TASK-0124 — DM assistant: session control commands (`!c agent/model/reset/status/…` in no-bound-repo DM)
- TASK-0125 — DM assistant: help text and README docs
