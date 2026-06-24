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
- TASK-0118 — Verify and document repo file upload workflow
