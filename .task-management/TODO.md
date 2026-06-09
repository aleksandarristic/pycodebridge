# TODO (Immediate)

Rules:
- Use stable task IDs in format `TASK-####`.
- IDs are immutable and never reused.
- Tasks promoted from `.task-management/BUGS.md` keep the same ID.
- When moving a task to backlog, keep the same ID.
- When completing a task, remove it from this file and append it to `.task-management/DONE.md`.
- When dropping a task, remove it from this file and append it to `.task-management/REMOVED.md`.

## Active tasks

- [TASK-0070] Per-session agent backend selection with `!agent` command.
  - Goal: let operators switch the agent backend per channel/session at runtime, resolved per run.
  - Scope:
    - Add `backend: str = ""` to `SessionState` (`sessions/state.py:18`) plus `from_dict` (line 168) and `to_dict` (line 220); empty falls back to `cfg.agent.default_backend`. Backward-compatible with existing state files.
    - Add `router.backend_for(channel_id, session) -> AgentBackend` (session backend -> factory, default fallback); replace the `router.runner.build_*` call sites (`handlers/core.py:69,109,124,126,129,267,269`; `commands/registry.py:745,749,751`) and the `run_codex` run call (`router.py:2026`).
    - New `!agent <name>` command mirroring the `!model` flow in `registry.py`; validate against known backends; persist `SessionState.backend`.
    - On backend switch: clear stored `thread_id` (cross-backend ids do not resume) and reset `model`/`effort` to the new backend's defaults, notifying the operator. Per-backend validation of `model`/`effort` (Codex effort set vs Claude `low|medium|high|xhigh|max`).
    - Config: add `agent.default_backend` (default `codex`); keep `cfg.codex.*`.
    - Audit/session-log: identify the backend per run (generalize `codex.exit`/`codex.error`/`codex.thread` event names or tag entries with backend).
  - Acceptance criteria:
    - Operator can switch backend per session; default Codex behavior is unchanged when `backend` is unset.
    - Switching clears the thread/session id and resets incompatible `model`/`effort` with a clear message.
    - Tests cover backend resolution, state round-trip with `backend`, the `!agent` command, and the switch-reset behavior.
  - Depends on: TASK-0069.
