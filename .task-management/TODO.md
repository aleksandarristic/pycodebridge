# TODO (Immediate)

Rules:
- Use stable task IDs in format `TASK-####`.
- IDs are immutable and never reused.
- Tasks promoted from `.task-management/BUGS.md` keep the same ID.
- When moving a task to backlog, keep the same ID.
- When completing a task, remove it from this file and append it to `.task-management/DONE.md`.
- When dropping a task, remove it from this file and append it to `.task-management/REMOVED.md`.

## Active tasks

- [TASK-0060] Document new bang shortcuts (`!new`, `!compact`, `!cpt`) in README and COMMAND_SURFACE.
  - Goal: bring user-facing docs in line with shortcuts added in 42e73ff.
  - Scope:
    - Add `!new` -> `choose new` and `!compact`/`!cpt` -> `choose compact` to `docs/COMMAND_SURFACE.md` (alongside the existing `!cont` entry).
    - Update `README.md` shortcut sections (~lines 211, 283) to list the new aliases and when they apply (while a conflict is pending).
  - Acceptance criteria:
    - Both files list all current `choose`-related shortcuts with accurate "while a conflict is pending" wording.
