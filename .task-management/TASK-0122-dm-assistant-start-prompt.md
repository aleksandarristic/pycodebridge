# TASK-0122 — DM assistant: start prompt builder

## Intent

Build a lightweight, dynamically-composed start prompt that gives the
assistant just enough context without bulk-loading the codebase.

## Scope

- Add `build_dm_assistant_prompt(router, event) -> str` in
  `codebridge/handlers/dm_admin.py` (or a new
  `codebridge/services/dm_assistant.py`).
- Prompt sections (in order):
  1. Role: "You are the pycodebridge assistant. You have access to the
     pycodebridge repo at {repo_path}. Answer questions about the bridge
     configuration, running sessions, and managed repos. Read docs on
     demand as needed."
  2. Key doc paths: README.md, DISCORD.md, AGENTS.md, docs/ — listed
     by path so the agent can read them if required, not pre-loaded.
  3. Repo list: current repos from `code_root` (names only, one per line).
  4. Active sessions summary: channel → session → backend/status, pulled
     from router state (compact, a few lines max).
  5. User memory: content of the user's memory file if it exists, with
     header "## Your memory for this user:"; omit section if empty.
  6. Memory file path: tell the agent where the memory file lives so it
     can update it using file tools.
- Keep total prompt under ~400 tokens for a typical deployment.
- Prompt is overridable via `dm_assistant.start_prompt` in config (same
  variable-substitution pattern as `codex.start_prompt`).
- Add unit tests for prompt assembly (mock router state).

## Acceptance Criteria

- Prompt includes repo list and active session summary drawn from live
  state.
- Memory section omitted when file is empty/absent.
- Prompt is under 400 tokens for a deployment with ≤20 repos and
  ≤10 active sessions.
