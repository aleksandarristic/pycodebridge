# TASK-0123 — DM assistant: routing and session lifecycle

## Intent

Route non-command DM messages to the assistant when no repo is bound,
reusing the existing session infrastructure.

## Scope

- In `_handle_dm_unprefixed` (dm_admin.py): when no repo is bound and
  `dm_assistant.enabled`, instead of returning the "No repo bound" error,
  call `handle_dm_assistant_prompt(router, event, sink, content)`.
- `handle_dm_assistant_prompt`:
  - Resolves the pycodebridge repo path (errors if not found in
    `code_root`).
  - Uses a fixed session key `"dm"` scoped to the DM channel (so
    `(channel_id, "dm")` is the session scope, consistent with existing
    per-(channel, session) state).
  - On first message or after session expiry: starts a new agent session
    with the built start prompt (TASK-0122) as the initial message.
  - On subsequent messages within TTL: resumes the existing session
    (`--continue`) with the user message as the next prompt.
  - Respects `session_idle_ttl_seconds` (from state config) — conflict
    prompt and `!c choose continue/new/compact` work exactly as in channels.
  - Runs directly in the pycodebridge repo directory (no worktree, per
    design decision).
  - Uses the backend/model configured for the `"dm"` session (from
    session state, defaulting to `dm_assistant.default_backend` and
    `dm_assistant.model`).
- TOTP: assistant prompts require default unlock (same as channel
  prompts). Enforce with existing `_totp_is_unlocked` check.
- Add integration tests: first message starts session, second message
  resumes, expired session triggers conflict prompt.

## Acceptance Criteria

- Non-command DMs route to the assistant when enabled and no repo is
  bound.
- Existing "No repo bound" error is shown when `dm_assistant.enabled:
  false`.
- Session continues across messages within TTL.
- Conflict prompt fires correctly on expiry.
