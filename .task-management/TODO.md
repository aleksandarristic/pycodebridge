# TODO (Immediate)

Rules:
- Use stable task IDs in format `TASK-####`.
- IDs are immutable and never reused.
- Tasks promoted from `.task-management/BUGS.md` keep the same ID.
- When moving a task to backlog, keep the same ID.
- When completing a task, remove it from this file and append it to `.task-management/DONE.md`.
- When dropping a task, remove it from this file and append it to `.task-management/REMOVED.md`.

## Active tasks

### Dispatch orchestrator (`feature/dispatch-orchestrator`)

- TASK-0099 — Dispatch parser: @agent extraction and fan-out detection
- TASK-0100 — DispatchConfig: dataclass + YAML loading + validation
- TASK-0101 — Orchestrator flow: task branch + sequential/parallel dispatch
- TASK-0102 — Dispatch output: per-agent status messages and aggregate summary
- TASK-0103 — Task close command: `!c done` with PR and merge modes
- TASK-0104 — Dispatch documentation and worked examples
