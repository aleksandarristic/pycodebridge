# Discord ↔ Codex CLI Bridge (Python) — Implementation Spec

## Goal
Build a Python service that bridges Discord channels to Codex CLI sessions:

- Listens in one Discord guild (server).
- Supports multiple channels named `codex-<reponame>`.
- A channel maps to a repo directory `<CODE_ROOT>/<reponame>`.
- Only messages starting with `!c` are forwarded to Codex (unless `allow_plain_prompts` is true).
- **One Codex session per channel** (multi-session names supported; default session name `default`).
- Uses **Codex CLI already signed in** on the host machine.
- For each `!c ...` message: run Codex CLI in non-interactive mode, stream output back to Discord “as-is”.
- Audit log all interactions per channel, per session, per thread.
- Provide explicit run control commands (`!c stop` to send ESC, `!c kill` to terminate the Codex process).

This is a “turn-based interactive” bridge: Codex asks questions in its output, users answer in subsequent `!c ...` messages, and we resume the same Codex session.

## Non-goals
- No extra safety gating for writes (Codex is allowed to write).
- No batching/debouncing of user messages.
- No interactive TUI automation by default (no PTY/ConPTY live sessions).
- No channel allowlists beyond channel name regex.

---

## Python stack choices
- **Python**: 3.14 (fallback 3.13/3.12 if needed).
- **Discord library**: `discord.py` 2.x.
- **Async model**: `asyncio` throughout; use `asyncio.create_subprocess_exec` for Codex runs.
- **Config**: YAML only.
- **Env loading**: `python-dotenv` from `.env` in repo root.
- **File locks**: `filelock`.
- **Tests**: `pytest`.
- **Logging**: stdlib `logging`, human-readable format.
- **Skills**: use repo-local skills in `.codex/skills` when tasks match (refactor, API stability, packaging/deps, performance triage, architecture review).

---

## Project layout (Python)

```
pycodebridge/
  cmd/
    bridge.py
  codebridge/
    __init__.py
    config.py
    discord_bot.py
    adapters/
      __init__.py
      discord.py
    router.py
    queue.py
    codex.py
    audit.py
    state.py
    logging.py
    transport.py
    util/
      __init__.py
      ansi.py
      chunk.py
      prompt.py
      path.py
  instructions/
    instructions.md
    tasks.md
  tests/
    ...
```

---

## Mapping model

- Discord channel name must match regex: `^codex-([A-Za-z0-9._-]+)$`
- `<reponame>` maps to a repo path: `<CODE_ROOT>/<reponame>`
- Protect against traversal and symlink escape outside `<CODE_ROOT>` (see **Security: Path containment**).

---

## Session model

One Codex session per Discord channel **per session name**:

- State stored locally:
  - `channel_id -> { sessions: { session_name -> { repo_name, repo_path, thread_id, created_at, last_used_at, model } }, sticky: { user_id -> session_name } }`
- `thread_id` is obtained from Codex JSONL event `thread.started`.
- Single active Codex process per channel+session; `!c resume` should attach to the existing session for that repo.
- Resume with `codex exec resume <thread_id> "<prompt>"`.
- If no `thread_id` exists: `codex exec resume --last "<prompt>"` in that repo directory, then store returned thread_id.
- Session limit per channel: **max 3 active sessions**.

---

## Codex invocation mode

Use **Codex CLI non-interactive exec** with JSONL output to support streaming:

- Start new session:
  - `codex exec --json --cd <repo_path> --sandbox workspace-write "<initial prompt>"`
- Resume by ID:
  - `codex exec --json --cd <repo_path> resume <thread_id> "<prompt>"`
- Resume last:
  - `codex exec --json --cd <repo_path> resume --last "<prompt>"`

Stream the agent’s text output to Discord by parsing JSONL events and extracting agent messages.

---

## Discord message flow

- Receive message create events.
- Ignore bot messages.
- If `allowed_user_ids` is non-empty, ignore commands from users not in the list.
- If message does not start with `!c` (prefix), ignore.
- Parse command/prompt after prefix.
- Resolve repo by channel name.
- Depending on command:
  - `!c start`, `!c resume`, `!c /quit`, `!c stop`, `!c kill`
  - `!c showrepo`, `!c showchanges`, `!c tests`, `!c logs <n>`, `!c config`
  - `!c thread <id>`, `!c choose resume|replace|cancel`
  - `!c status` / `!c help`
  - `!c git ...`, `!c ps`, `!c cancel`, `!c rerun`, `!c peek`, `!c stats`
  - `!c use <session>` (alias `select`)
  - `!c model [session] <id>`
  - `!c spec`, `!c createrepo`, `!c clonerepo`, `!c copyrepo`
  - otherwise: treat as prompt to Codex in that channel session

Send Codex output back to the same channel.

---

## Transport abstraction

- The Router consumes a platform-agnostic `MessageEvent` plus a `ResponseSink` interface.
- `MessageEvent` carries normalized channel/user metadata and the raw content.
- `ResponseSink` exposes `send()`, `typing()` and `update_pinned_status()` for platform adapters.
- Discord-specific wiring lives in an adapter that translates discord.py messages into `MessageEvent` and `ResponseSink`.

---

## Configuration (YAML only)

Example `config.yaml`:

```yaml
discord:
  token_env: "DISCORD_TOKEN"
  guild_id: ""
  allowed_user_ids: []
  prefix: "!c"
  channel_name_regex: "^codex-([A-Za-z0-9._-]+)$"
  max_discord_message_chars: 1800
  allow_plain_prompts: false
  dm_admin_enabled: false
  dm_admin_user_ids: []

codex:
  binary: "codex"
  code_root: "/home/you/Code"
  sandbox: "workspace-write"
  json: true
  start_prompt: |
    Hello. This is a Discord-bridged Codex session for repo: {{REPO_NAME}}.
    Operate inside this repo directory. Stream outputs plainly.
  model: ""
  env: {}

state:
  data_dir: "/home/you/.discord-codex-bridge"
  lock_timeout_seconds: 600
  conflict_ttl_seconds: 60
  log_dir: "/home/you/.discord-codex-bridge/logs"

runtime:
  log_level: "info"

transport:
  adapter: "discord"

repo_bootstrap:
  agents_template: ""
  spec_prompt: ""
```

---

## Env vars

- Discord token must come from env: `DISCORD_TOKEN` (or configured key).
- Codex is assumed signed-in already; no API key needed here.

---

## Security: Path containment

Mandatory for all repo path resolution.

Rules:
1) Validate `repo_name` against `^[A-Za-z0-9._-]+$` and deny separators or traversal.
2) `code_root_abs = abs(clean(expand(code_root)))`
3) `repo_abs = abs(clean(join(code_root_abs, repo_name)))`
4) Resolve symlinks for both; if resolution fails, use raw path.
5) Check `repo_real` is within `code_root_real` using `relpath` and ensure it does not start with `..`.
6) Ensure `repo_real` exists and is a directory.
7) Require `.git` to exist (non-git repos are not allowed yet).

If any check fails: refuse and respond in Discord with a short error.

---

## State & logs

### State file
Stored at: `<data_dir>/state.json`

```json
{
  "version": 1,
  "channels": {
    "<channel_id>": {
      "sessions": {
        "default": {
          "repo_name": "reponame",
          "repo_path": "/abs/path/to/repo",
          "thread_id": "thread_...",
          "model": "",
          "created_at": "2026-01-23T12:00:00Z",
          "last_used_at": "2026-01-23T12:34:56Z"
        }
      },
      "sticky": {
        "<user_id>": "default"
      }
    }
  }
}
```

Use `filelock` to guard against concurrent writers.

### Audit logs

Directory layout:

```
<log_dir>/
  <channel_id>/
    <session_name>/
      <thread_id>/
        000001.request.json
        000001.codex.jsonl
        000001.discord_out.txt
        000001.codex.stderr.txt
```

For each incoming `!c ...` message, log:
- metadata: timestamp, guild_id, channel_id, message_id, author_id, author_name
- repo_name, repo_path
- thread_id before/after
- the user prompt / command
- raw Codex JSONL output
- exact text sent to Discord (per chunk)

Sequence numbers should be monotonic per thread directory.

---

## Commands: exact behavior

Follow behavior described in the Go spec (ported):
- `help`, `status`, `stats`, `peek`
- `start`, `resume`, `choose resume|replace|cancel`, `use/select`, `model`, `thread`
- `stop`, `kill`, `/quit`
- `showrepo`, `showchanges`, `tests`, git helpers
- queue controls `ps`, `cancel`, `rerun`
- repo bootstrap `createrepo`, `clonerepo`, `copyrepo`, `spec`
- DM admin commands (optional, gated by config) for repo management

All invalid/forbidden actions should respond:

```
I'm sorry, Dave. I'm afraid I can't do that.
```

Followed by a fenced text block describing the reason.

---

## Streaming output back to Discord

### JSONL parsing

- Read stdout line-by-line.
- Append raw lines to audit `codex.jsonl`.
- Parse JSONL events and extract agent messages.
- Capture thread_id on `thread.started`.
- Detect user-input prompts and prefix with `Codex asks:`.

### Message chunking and formatting

- Chunk by `max_discord_message_chars` (default 1800).
- Strip ANSI/control codes.
- Wrap diffs in fenced ```diff blocks when possible.

---

## Concurrency & robustness

- Per-channel queue; sequential processing.
- No hard timeouts on Codex runs.
- Run control: `stop` (ESC then SIGINT), `kill` (force terminate).
- Keep typing indicator alive during runs and while reporting queued state.

---

## Acceptance checks (manual)

- Routing: non-matching channels ignored; prefix required.
- Repo mapping: channel name to repo path with containment and `.git` check.
- Session lifecycle: start/resume/quit; restart recovery.
- Conflicts: `!c start` prompts `choose` if session exists.
- Queue: ordered processing; `ps`, `cancel`, `rerun`.
- Run control: stop/kill; no hard timeout.
- Formatting: ANSI stripped, diffs fenced, chunking enforced.
- DM admin (if enabled) commands work and are restricted by allowlist.
