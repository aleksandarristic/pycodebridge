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
- [TASK-0007] Parametrize TOTP requirements in config for command groups.
  - Goal: allow configuration of TOTP enforcement for privileged commands rather than hard-coding behavior.
  - Scope:
    - Add config controls for TOTP requirements on `!git` commands.
    - Add config controls for TOTP requirements on `!gh` commands.
    - Add config controls for other commands that currently require TOTP even when a user session is unlocked.
  - Acceptance criteria:
    - Operators can enable/disable TOTP requirements per configured command group.
    - Existing defaults remain backward compatible unless config is explicitly changed.
    - Help/docs clearly describe the new config knobs and default behavior.
    - Add targeted tests for command authorization behavior with TOTP required vs not required.
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

- [TASK-0011] Discord-only transport surface; remove Telegram/Slack wiring while preserving modular transport architecture.
  - Goal: keep Discord as the only active/supported transport and remove Telegram/Slack runtime/docs surface, without coupling router/handler logic to Discord-specific types.
  - Scope:
    - Remove Telegram/Slack runtime entrypoint wiring and adapter-selection paths from startup flow.
    - Remove Telegram/Slack user docs and configuration examples from primary docs/config templates.
    - Keep transport abstractions (`MessageEvent`, `ResponseSink`, capability contracts, router boundaries) intact so future transports can be dropped in with new adapters.
    - Clean up/adjust targeted tests to reflect Discord-only support while retaining modular interface coverage.
  - Acceptance criteria:
    - Bridge runs only with Discord transport configuration; Telegram/Slack are not documented as active options.
    - Transport-agnostic interfaces remain in place and continue to be used across router/handlers/services.
    - Updated docs clearly describe Discord-only support and how future transport adapters can be reintroduced.
    - Targeted tests for startup/config/docs-linked behavior pass.
