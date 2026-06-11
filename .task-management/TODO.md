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

- [TASK-0083b] Heartbeat ping message shows agent, model, and effort.
  - Context: The heartbeat (emitted every `run_heartbeat_seconds`) currently says:
    `"Still running in session 'default' (2m elapsed)."` — no hint of what's actually running.
  - Goal: enrich the message to read e.g.:
    `"Gemini (gemini-2.5-pro) working for 2m with yolo effort."` or
    `"Claude (claude-sonnet-4-6) working for 2m with high effort."` or
    `"Codex (gpt-5.4-codex) working for 2m."` (no effort clause for Codex when it's the default,
    but include it when a non-default effort is set).
    Omit the effort clause entirely for Gemini (no effort concept) and when effort is unset/default.
    Include the session name only when it's not `"default"` (to avoid noise in the common case).
  - Scope:
    - `_run_heartbeat` (`router.py:2324`) currently receives only `sink`, `session`,
      `started_at`. Extend its signature to also accept `backend_name: str`, `model: str`,
      `reasoning_effort: str` — all already available as locals in `run_codex` at the
      `create_task` call site (`router.py:2109`).
    - Build a helper (private to `router.py` or inline) that produces the formatted prefix:
      `"{BackendDisplay} ({model}) working for {elapsed}"` where:
        - `BackendDisplay` = capitalised backend name (`Gemini`, `Claude`, `Codex`); use the
          backend's class name or the `backend_name` string.
        - `model` = active model if set, else omit the parenthetical entirely.
        - effort clause = `" with {effort} effort"` appended only when `reasoning_effort` is
          non-empty AND `backend_name != "gemini"`.
        - Session clause = `" in session '{session}'"` appended only when `session` differs
          from `DEFAULT_SESSION`.
    - Example outputs:
        - `"Gemini working for 2m."` (no model override, no effort, default session)
        - `"Gemini (gemini-2.5-pro) working for 2m."` (model set, default session)
        - `"Claude (claude-sonnet-4-6) working for 4m with high effort in session 'feat'."` (all fields)
        - `"Codex working for 1m."` (nothing set, default session)
  - Implementation notes:
    - `backend_name`, `model`, and `reasoning_effort` are already resolved locals in
      `run_codex` by the time `heartbeat_task` is created — no extra state lookup needed.
    - The Gemini no-effort rule mirrors `_normalize_effort_for_backend` returning `None`
      for `bn == "gemini"` — keep that as the canonical check, don't duplicate the logic.
    - Keep the change isolated to `_run_heartbeat` and its single call site; no other
      methods need touching.
  - Acceptance criteria:
    - Heartbeat message includes backend name (always), model in parens (when set),
      effort clause (when set and not Gemini), session clause (when non-default).
    - Gemini runs never include an effort clause regardless of what `reasoning_effort` holds.
    - Default session runs omit the session clause.
    - Existing `_run_heartbeat` tests (if any) updated; new tests cover the Gemini/Claude/Codex
      variants with and without model/effort/session overrides.
