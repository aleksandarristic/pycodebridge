# TODO (Immediate)

Rules:
- Use stable task IDs in format `TASK-####`.
- IDs are immutable and never reused.
- Tasks promoted from `.task-management/BUGS.md` keep the same ID.
- When moving a task to backlog, keep the same ID.
- When completing a task, remove it from this file and append it to `.task-management/DONE.md`.
- When dropping a task, remove it from this file and append it to `.task-management/REMOVED.md`.

## Active tasks

- [TASK-0083] `!agent`, `!model`, `!effort` with no args show current session selection.
  - Context: All three commands currently reject a bare call (no args) with a usage error.
    A zero-arg call is the natural way to ask "what is currently set?" — consistent with how
    most CLI tools work and how `!efforts` / `!models` already work (they list, not mutate).
  - Goal: make `!c agent`, `!c model`, and `!c effort` (bare, optionally with just a session
    name) display the current effective backend, model, and effort for the session instead of
    returning a usage error.
  - Scope:
    - In `_cmd_agent` (`registry.py:824`): when `rest` is empty (or only a session name),
      read the current backend via `_backend_name_for_session` and reply with e.g.:
      `"Session 'default' backend: gemini (configured default)"` — note whether it's a
      session override or the configured `agent.default_backend`.
    - In `_cmd_model` (`registry.py:706`): when `rest` is empty (or only a session name),
      read `router.session_model(channel_id, session)` and reply with e.g.:
      `"Session 'default' model: gemini-2.5-pro (override) / (configured default)"`.
    - In `_cmd_effort` (`registry.py:897`): when `rest` is empty (or only a session name),
      read `router.session_reasoning_effort(channel_id, session)` and reply similarly.
      For Gemini sessions the reply should note effort is not supported, not error.
    - Optionally: expose a combined `!c session` / make bare `!c agent` show all three in
      one reply (backend + model + effort) as a single status line — evaluate during
      implementation.
    - Session-name disambiguation: a lone token that isn't a backend name / effort level
      should be treated as a session name (same logic as existing mutating paths).
  - Implementation notes:
    - Reading state for a display-only call must never create the session — use
      `session_exists(state, ...)` guard or load state read-only before replying.
    - The reply should clearly distinguish between "override active" and "using configured
      default" so the user knows whether `!model default` / `!effort default` would change
      anything.
    - `_cmd_effort` currently gates Gemini sessions with `reply_forbidden`; the no-arg path
      should skip that gate and instead say effort is not applicable for Gemini, not forbidden.
  - Acceptance criteria:
    - `!c agent` (bare) replies with the current backend name and whether it's a session
      override or the configured default; does not error.
    - `!c model` (bare) replies with the current model and override/default status.
    - `!c effort` (bare) replies with the current effort and override/default status, or a
      polite "not applicable" for Gemini — not a forbidden/usage error.
    - All three accept an optional leading session name token (`!c model mysession`).
    - No session is created as a side-effect of the read.
    - Tests cover: bare call on default session, bare call with explicit session name, Gemini
      session no-arg effort, and at least one case where a session override is active vs. none.
