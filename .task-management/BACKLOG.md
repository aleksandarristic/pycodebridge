# BACKLOG

Rules:
- Use stable task IDs in format `TASK-####`.
- IDs are immutable and never reused.
- Bugs moved from `.task-management/BUGS.md` keep the same ID.
- When promoting a task to immediate TODO, move the task block to `.task-management/TODO.md` and keep the same ID.
- When completing a task, remove it from this file and append it to `.task-management/DONE.md`.
- When dropping a task, remove it from this file and append it to `.task-management/REMOVED.md`.

## Backlog tasks

- [TASK-0002] Final-message ordering hardening for run lifecycle output.
  - Goal: prevent stale/intermediate progress updates from appearing after a run-complete message.
  - Scope:
    - Emit a single authoritative terminal event for each run (success/failure/cancelled).
    - Suppress or ignore late progress events once terminal state is set.
    - Add clear run-state metadata so transports can order/filter consistently.
  - Acceptance criteria:
    - After terminal event emission, no additional progress update is delivered for that run.
    - User-visible last message is always terminal status for the run.
    - Regression test covers out-of-order event delivery scenario.

- [TASK-0003] Compose + global skill defaults for cross-repo persistence (deferred).
  - Goal: define and document a non-`AGENTS.md` channel for durable operator defaults across repos/sessions.
  - Approach:
    - Use user-level Codex skills persisted in mounted Codex home (`CODEX_AUTH_HOST -> /workspace/home/.codex` in Compose).
    - Optionally set `codex.env.CODEX_HOME=/workspace/home/.codex` in `config.docker.yaml` for explicit subprocess behavior.
  - Deliverables:
    - Add docs snippet with host-side skill path, minimal `SKILL.md` example, and Compose restart/apply steps.
    - Clarify precedence/coexistence with per-repo `AGENTS.md`.

- [TASK-0004] Role-based permissions model (Discord-role driven access tiers).
- [TASK-0005] Knowledge shortcuts/macros for repeatable repo workflows.
- [TASK-0006] Web-based/dashboard features (status/admin web surface, browser ops views).
