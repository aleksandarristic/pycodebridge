# Codex CLI Bridge (Python)

Bridge transport channels (`codex-<repo>`) to Codex CLI sessions in local repos under `code_root`. One channel maps to one Codex session with queueing, multi-session support, and run control.

## Features
- Map `#codex-<repo>` to `<code_root>/<repo>` (must exist, be inside root, and contain `.git`).
- Stream Codex JSONL output to transports; strip control codes; flag prompts needing user input.
- Per-channel queue, multi-session support (max 3 per channel), run control (stop/kill/quit).
- Optional DM admin mode for owner-only repo management (Discord).
- Transport-agnostic router (`MessageEvent` + `ResponseSink`).

## Integrations
- Discord (supported): `DISCORD.md`
- Telegram (supported via long polling): `TELEGRAM.md`
- Slack (scaffold only): `SLACK.md`

## Transport capabilities
Adapters declare capabilities for threads, replies, uploads, downloads, and typing. Router behavior is gated by these flags.
- Discord: threads ✅, replies ❌, uploads ✅, downloads ✅, typing ✅
- Telegram: threads ✅ (topics), replies ✅, uploads ✅, downloads ✅, typing ✅ (chat action)
- Slack: scaffold only (capabilities disabled until implemented)

## Setup
Prereqs:
- Python 3.14+ (3.13/3.12 fallback)
- Codex CLI installed and signed in (binary on PATH or set `codex.binary`).
- Discord bot token with Message Content intent enabled (current adapter).

Quick start:
1) Create `config.yaml` (start from `config.example.yaml`).
2) Set `DISCORD_TOKEN` (or the env named by `discord.token_env`) in `.env` at the repo root.
3) Optional: `pip install -e .` for an editable install.
4) Run: `./.venv/bin/python -m cmd.bridge -config config.yaml` (or `./.venv/bin/python -m codebridge -config config.yaml`)

## Configuration reference
Paths support `$VAR`/`%APPDATA%`/`~` expansion.

### `discord`
- `token_env` (default `DISCORD_TOKEN`) — environment variable containing bot token.
- `guild_id` (default empty) — restrict to a single server ID if set.
- `allowed_user_ids` (default empty) — allowlist for channel commands; if non-empty, ignore others.
- `prefix` (default `!c`) — command prefix.
- `channel_name_regex` (default `^codex-([A-Za-z0-9._-]+)$`) — maps channel to repo name.
- `allow_plain_prompts` (default `false`) — treat non-prefixed messages as prompts in matching channels.
- `dm_admin_enabled` (default `false`) — enable DM admin commands.
- `dm_admin_user_ids` (default empty) — allowlist for DM admin (falls back to `allowed_user_ids`).
- `max_discord_message_chars` (default `1800`) — outbound chunk size.

### `telegram`
- `token_env` (default `TELEGRAM_TOKEN`) — environment variable containing bot token.
- `allowed_user_ids` (default empty) — allowlist for channel commands; if non-empty, ignore others.
- `prefix` (default `!c`) — command prefix.
- `channel_name_regex` (default `^codex-([A-Za-z0-9._-]+)$`) — maps chat title to repo name.
- `allow_plain_prompts` (default `false`) — treat non-prefixed messages as prompts in matching chats.

### `codex`
- `binary` (default `codex`) — path/name of Codex CLI.
- `code_root` (required) — directory containing git repos.
- `sandbox` (default `workspace-write`) — Codex sandbox mode.
- `json` (default `true`) — JSONL streaming output (required).
- `start_prompt` (default template) — prompt used for new sessions.
- `model` (default empty) — default model; override per session with `!c model`.
- `env` (default `{}`) — extra environment variables for Codex.

### `state`
- `data_dir` (required) — directory for state.json and locks.
- `log_dir` (required) — directory for audit logs and `bridge.log`.
- `lock_timeout_seconds` (default `600`) — stale lock timeout.
- `conflict_ttl_seconds` (default `60`) — conflict prompt TTL.

### `runtime`
- `log_level` (default `info`) — `debug|info|warn|error`.

### `audit`
- `redact` (default `false`) — redact secrets from audit logs before writing.
- `redact_patterns` (default `[]`) — optional regex patterns to redact.

### `transport`
- `adapter` (default `discord`) — transport adapter to use (`discord`/`telegram` supported; `slack` scaffold only).

### `repo_bootstrap`
- `agents_template` (default empty) — optional AGENTS.md template for `!c createrepo`.
- `spec_prompt` (default template) — prompt used by `!c spec`.

## Commands
Prefix default is `!c`. Channels should be named `codex-<repo>`.

General:
- `!c help`, `!c status`, `!c config`, `!c stats [session]`, `!c peek [session]`

Sessions:
- `!c start [session]`
- `!c resume [session] [prompt]`
- `!c choose [session] resume|replace|cancel`
- `!c use <session>` (alias `select`)
- `!c model [session] <id>`
- `!c thread [session] <id>`

Repo bootstrap:
- `!c createrepo`
- `!c clonerepo <url>`
- `!c copyrepo <newname>`
- `!c spec [session]`

Run control:
- `!c stop [session]` (ESC then SIGINT)
- `!c kill [session]`
- `!c /quit [session]`

Repo helpers:
- `!c showrepo`
- `!c showchanges`
- `!c tests`
- `!c git <status|log|branches|show|diff|pull|commit|push|merge> [...]`
- `!c download <path>`

Queue:
- `!c logs [session] [n]`
- `!c ps`
- `!c cancel <job-id>`
- `!c rerun`

Passthrough:
- Any other `!c` text is sent as a prompt to Codex.

## DM admin commands (optional)
Enable with `discord.dm_admin_enabled: true`. Commands require the same `!c` prefix in DMs (Discord only).

- `!c help`
- `!c repos`
- `!c sessions`
- `!c status`
- `!c config`
- `!c createrepo <name>`
- `!c clonerepo <name> <url>`
- `!c copyrepo <from> <to>`
- `!c deleterepo <name>` (alias: `delete`)
- `!c renamerepo <from> <to>` (alias: `rename`)

When a repo is bound in DMs, any message without `!c` is treated as a prompt.
Attachments in channels or bound DMs will prompt for a destination path before saving.

## Troubleshooting
- No response: confirm Message Content intent is enabled and saved, and your user ID is allowlisted.
- Repo error: ensure channel name matches `codex-<repo>` and `<code_root>/<repo>/.git` exists.
- DM admin: enable `discord.dm_admin_enabled` and ensure `dm_admin_user_ids` or `allowed_user_ids` includes you.

## Docs
- Architecture diagram (Mermaid): `docs/architecture.mmd`
- Slack setup: `SLACK.md`
- Telegram setup: `TELEGRAM.md`
