# TODO (Immediate)

Rules:
- Use stable task IDs in format `TASK-####`.
- IDs are immutable and never reused.
- Tasks promoted from `.task-management/BUGS.md` keep the same ID.
- When moving a task to backlog, keep the same ID.
- When completing a task, remove it from this file and append it to `.task-management/DONE.md`.
- When dropping a task, remove it from this file and append it to `.task-management/REMOVED.md`.

## Active tasks

- [TASK-0008] Broaden known `!git` command coverage (for example: `add`, `fetch`).
  - Goal: expand the allowlisted/known `!git` subcommands so common workflows are supported without manual workarounds.
  - Scope:
    - Add missing high-utility subcommands (including `add` and `fetch`) to known command handling.
    - Ensure parsing/validation and security gates remain consistent with existing `!git` behavior.
    - Update user-facing help/docs for the expanded command set.
  - Acceptance criteria:
    - New subcommands are accepted and routed correctly via `!git`.
    - Unsupported/dangerous commands remain blocked by policy.
    - Add targeted tests covering added commands and rejection behavior.
