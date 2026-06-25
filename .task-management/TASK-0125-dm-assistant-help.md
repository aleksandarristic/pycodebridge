# TASK-0125 — DM assistant: help and user-facing docs

## Intent

Document the DM assistant in help text and README so users know it
exists and how to use it.

## Scope

- Update `_dm_help_text()` in dm_admin.py to include an "Assistant"
  section when `dm_assistant.enabled`:
  - Explain: messages without a command go to the bridge assistant.
  - List: `!c agent`, `!c model`, `!c effort`, `!c reset`, `!c status`,
    `!c choose`, `!c logs`.
  - Note memory: the assistant maintains a per-user memory file it can
    update during conversation.
- Update README.md:
  - New `## DM assistant` section after `## DM admin commands`.
  - Covers: enabling (`dm_assistant.enabled: true`), what the assistant
    knows (repos, sessions, pycodebridge docs), session lifecycle, memory,
    backend selection.
  - Config reference: document all `dm_assistant.*` keys in
    `## Configuration reference`.
- Update `config.example.yaml` and `config.docker.example.yaml` with
  documented `dm_assistant` block (commented out by default).

## Acceptance Criteria

- `!c help` in DM shows the assistant section when enabled.
- README covers enabling, using, and configuring the DM assistant.
- Config examples include all `dm_assistant` keys with comments.
