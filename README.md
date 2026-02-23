# Codex CLI Bridge (Python)

Bridge transport channels (`codex-<repo>`) to Codex CLI sessions in local repos under `code_root`. One channel maps to one Codex session with queueing, multi-session support, and run control.

## Features
- Map `#codex-<repo>` to `<code_root>/<repo>` (must exist, be inside root, and contain `.git`).
  Repo identifiers are canonicalized to lowercase.
- Stream Codex JSONL output to transports; strip control codes; flag prompts needing user input.
- Per-channel queue, multi-session support (max 3 per channel), run control (stop/interrupt/kill/quit).
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
4) Run locally: `./run.sh`
   - Direct Python entrypoint still works: `./.venv/bin/python -m cmd.bridge -config config.yaml` (or `./.venv/bin/python -m codebridge -config config.yaml`)
   - Preflight only: `./run.sh --check`

## Docker quick start
1) Copy Docker config: `cp config.docker.example.yaml config.docker.yaml`
2) Set mounts (shell export or `.env` in repo root):
   - `CODE_ROOT_HOST=/absolute/path/to/repos`
   - `STATE_DIR_HOST=/absolute/path/to/pycodebridge-state`
   - `CODEX_AUTH_HOST=/absolute/path/to/codex-auth-dir` (optional; defaults to `./.docker-codex-auth`)
   - `GH_CONFIG_HOST=/absolute/path/to/gh-config-dir` (optional; defaults to `./.docker-gh-config` in Compose)
   - `HOST_UID=$(id -u)` and `HOST_GID=$(id -g)` (required for Compose)
   - To reuse existing host Codex login in Compose, set `CODEX_AUTH_HOST=$HOME/.codex`
   - If `STATE_DIR_HOST` is omitted, default is `./.docker-state`
3) Preflight only: `./run_docker.sh --check`
4) Run container: `./run_docker.sh`
5) First-time Codex auth in Docker (if not already authenticated in mounted auth dir):
   - `docker exec -it pycodebridge codex login --device-auth`
6) Headless with Compose: `docker compose up -d --build`
7) Full Docker details: `DOCKER.md`
8) One-shot update + redeploy:
   - Preflight only: `./update.sh --check`
   - Update current branch and redeploy: `./update.sh`
   - Update a specific branch and redeploy: `./update.sh main`
9) Optional health endpoint:
   - Set `runtime.health_bind` (example: `127.0.0.1:8080`)
   - Optional path: `runtime.health_path` (default `/healthz`)
   - Probe: `curl -fsS http://127.0.0.1:8080/healthz`
10) Reset persisted bridge state quickly:
   - `./reset_state.sh` (uses running Compose container when available, else host state dir)
   - Optional explicit host path: `./reset_state.sh /absolute/path/to/state`

## Configuration reference
Paths support `$VAR`/`%APPDATA%`/`~` expansion.

### `discord`
- `token_env` (default `DISCORD_TOKEN`) — environment variable containing bot token.
- `guild_id` (required for Discord adapter) — restrict to a single server ID. Bot rejects other guilds and auto-leaves them on startup/join.
- `allowed_user_ids` (required, non-empty) — allowlist for channel commands; users outside this list are rejected.
- `prefix` (default `!c`) — command prefix.
- `channel_name_regex` (default `^codex-([A-Za-z0-9._-]+)$`) — maps channel to repo name.
- Discord repo channels must be private (`@everyone` cannot view); messages in non-private Discord channels are ignored.
- `allow_plain_prompts` (default `false`) — treat non-prefixed messages as prompts in matching channels.
- `dm_admin_enabled` (default `false`) — enable DM admin commands.
- `dm_admin_user_ids` (default empty) — allowlist for DM admin (falls back to `allowed_user_ids`).
- `totp_enabled` (default `false`) — require TOTP for protected commands on all platforms.
- `totp_secret_env` (default `DISCORD_TOTP_SECRET`) — env var containing Base32 TOTP secret.
- `totp_window` (default `1`) — accepted clock skew window in 30s steps.
- `totp_max_failures` (default `5`) — invalid/replayed TOTP attempts allowed before lockout (`0` disables lockout).
- `totp_failure_window_seconds` (default `300`) — rolling window used when counting failed attempts.
- `totp_cooldown_seconds` (default `300`) — lockout duration after too many failures (`0` disables lockout).
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
- `ask_for_approval` (default empty) — optional Codex approval policy (`untrusted|on-failure|on-request|never`).
- `network_access` (default `false`) — when `true` and sandbox is `workspace-write`, add `-c sandbox_workspace_write.network_access=true`.
- `json` (default `true`) — JSONL streaming output (required).
- `start_prompt` (default template) — prompt used for new sessions.
- `model` (default empty) — default model; override per session with `!c model`.
- `env` (default `{}`) — extra environment variables for Codex.

### `state`
- `data_dir` (required) — directory for state.json and locks.
- `log_dir` (required) — directory for audit logs and `bridge.log`.
- `lock_timeout_seconds` (default `600`) — stale lock timeout.
- `conflict_ttl_seconds` (default `60`) — conflict prompt TTL.
- `session_idle_ttl_seconds` (default `0`) — when >0, sessions idle longer than this require explicit `continue` or `new` before resuming.

### `runtime`
- `log_level` (default `info`) — `debug|info|warn|error`.
- `health_bind` (default empty) — optional health HTTP bind (`<host>:<port>` or `<port>`).
- `health_path` (default `/healthz`) — health endpoint path.
- `run_heartbeat_seconds` (default `120`) — interval for "still running" status messages.
- `run_completion_min_seconds` (default `300`) — minimum run duration before posting completion summary.
- `show_reasoning_details` (default `true`) — include reasoning level text in status/pinned output.

### `audit`
- `redact` (default `false`) — redact secrets from audit logs before writing.
- `redact_patterns` (default `[]`) — optional regex patterns to redact.

### `transport`
- `adapter` (default `discord`) — transport adapter to use (`discord`/`telegram` supported; `slack` scaffold only).

### `git`
- `enabled` (default `false`) — enable automatic git bootstrap configuration.
- `user_name` (default empty) — sets `git config user.name` globally (or local fallback).
- `user_email` (default empty) — sets `git config user.email` globally (or local fallback).
- `credential_helper` (default `!gh auth git-credential`) — sets git credential helper for non-interactive pushes.
- `global_config_path` (default empty) — optional path passed as `GIT_CONFIG_GLOBAL` during bootstrap.
- `apply_on_startup` (default `true`) — apply bootstrap at app startup.
- `apply_to_existing_repos` (default `true`) — when global bootstrap fails and local fallback is enabled, apply settings to existing repos.
- `apply_on_repo_create_clone_copy` (default `true`) — apply local settings automatically after `!c create`, `!c clone`, and `!c copy`.
- `local_fallback_on_global_failure` (default `true`) — if global config write fails, try repo-local config instead.
- `allow_dangerous_ops` (default `false`) — allow dangerous git helper operations (force push, branch delete) when explicitly enabled.
- `require_confirmation_for_dangerous_ops` (default `true`) — require explicit confirmation token for dangerous git helper operations.
- `dangerous_confirmation_token` (default `--confirm-dangerous`) — confirmation token required when dangerous git helper operations are enabled.

### `repo_bootstrap`
- `agents_template` (default empty) — optional AGENTS.md template for `!c create`.
- `spec_prompt` (default template) — prompt used by `!c spec`.

## Commands
Prefix default is `!c`. Channels should be named `codex-<repo>`.
When `discord.totp_enabled: true`, use `!c unlock <totp> [ttl]` to unlock default commands for your account (`30m`, `1h`, `2h`; default `1h`).
Use `!c unlock gh <totp> [ttl]` for GitHub CLI commands, or `!c unlock all <totp> [ttl]` to unlock both scopes.
Use `!c unlock extend [gh|all] <ttl> --totp <code>` to extend active unlock windows.
Use `!c unlock [gh|all] status` or `!c lock status [gh|all]` to check remaining time.
Use `!c lock [gh|all]` to clear unlock windows (`!c lock` clears all scopes).
Use `!c lock extend [gh|all] <ttl> --totp <code>` to extend active unlock windows (`30m`, `1h`, `2h`, etc.).
While default scope is unlocked, plain chat prompts are accepted even if `allow_plain_prompts` is `false`.
Failed/replayed TOTP attempts are rate-limited per user (`platform:user_id`) using the limiter settings above.

TOTP not required (open in channel):
- `!c help`
- `!c help <command>`
- `!help` (top-level shortcut for `!c help`)
- `!c status`
- `!c stats [session]`
- `!c peek [session]`
- `!c updates`
- `!c models [session]`
- `!c show` (alias: `showrepo`)
- `!c changes` (alias: `showchanges`)
- `!c ps`
- `!c unlock [gh|all] status`
- `!c lock [gh|all]`
- `!c lock status [gh|all]`
- `!unlock ...`, `!ul ...`, `!lock ...` (top-level shortcuts for `!c unlock ...` / `!c lock ...` in mapped repo channels)

TOTP always required (high-risk in channel):
- `!c unlock [gh|all] [ttl]`
- `!c unlock extend [gh|all] <ttl>`
- `!c lock extend [gh|all] <ttl>`
- `!c create` (aliases: `createrepo`, `new`)
- `!c clone <url>` (alias: `clonerepo`)
- `!c copy <newname>` (aliases: `copyrepo`, `cp`)
- High-risk git remote mutations: `!c git remote set-url ...`, `!c git remote add ...`, `!c git remote remove ...`, `!c git remote rename ...`, `!c git remote set-head ...`
- Upload flows (attachment submit and upload-path response)

TOTP required for GitHub CLI unless gh scope is unlocked:
- `!c gh <args>`
- `!gh <args>` (shortcut for `!c gh <args>`)

TOTP required unless the chat is unlocked:
- `!c start [session]`
- `!c resume [session] <prompt>`
- `!c choose [session] continue|new|cancel`
- `!c use <session>` (alias `select`)
- `!c model [session] <id> [reasoning]`
- `!c thread [session] <id>`
- `!c reset [session]`
- `!c spec [session]`
- `!c stop [session]`
- `!c interrupt [session]` (alias: `esc`)
- `!c kill [session]`
- `!c /quit [session]`
- Shortcut: `!stop [session]` (maps to `!c interrupt [session]` in mapped repo channels)
- Shortcut: `!pause [session]` (maps to `!c interrupt [session]` in mapped repo channels)
- `!c steer [session] -- <text>` or `!c steer <text>`
- Shortcut: `!steer <text>` (maps to `!c steer <text>` in mapped repo channels)
- Shortcut: `!s <text>` (maps to `!c steer <text>` in mapped repo channels)
- Shortcut: `!s:<session> <text>` (maps to `!c steer <session> -- <text>` in mapped repo channels)
- `!c answer [session] -- <text>` or `!c answer <text>`
- Shortcut: `!a <text>` (maps to `!c answer <text>` in mapped repo channels)
- Shortcut: `!a:<session> <text>` (maps to `!c answer <session> -- <text>` in mapped repo channels)
- `!c approve [session]` (sends `yes`)
- Shortcut: `!y` (maps to `!c approve`)
- `!c deny [session]` (sends `no`)
- Shortcut: `!n` (maps to `!c deny`)
- `!c wait` (show sessions currently awaiting input)
- Shortcut: `!w` (maps to `!c wait`)
- `!c cancel <job-id>`
- `!c rerun`
- Shortcut: `!retry` (maps to `!c rerun`)
- `!c config`
- `!c tests`
- `!c download <path>`
- `!c logs [session] [n]`
- Shortcut: `!log [n]` (maps to `!c logs [n]`)
- `!c git <status|log|branches|branch|show|diff|remote|fetch|pull|add|commit|push|merge>`
- Shortcut: `!git ...` (maps to `!c git ...`)
- Any other prompt-style `!c ...` command that is not in the read-only list
- Plain prompts in mapped channels when `allow_plain_prompts: true`

Auth tags used by `!c help`:
- `[open]` no TOTP needed.
- `[unlock/default]` requires default unlock (or `--totp`).
- `[unlock/gh]` requires gh unlock (or `--totp`).
- `[totp]` always requires `--totp`.
- `[mixed]` depends on command mode.

General:
- `help` (alias: `commands`) `[open]`
- `help <command>` for command-specific details and examples (for example `!c help git`)
- `status` (alias: `st`), `stats` (alias: `usage`), `peek` (alias: `pk`), `updates` (aliases: `update`, `version`) `[open]`
- Top-level shortcuts in mapped repo channels: `!st` -> `!c status`, `!u` -> `!c updates`
  - `status` includes contextual `Related:` hints (for example `!c start`, `!ps`, `!w`) when relevant.
  - `status` also shows lock state for your account (`default` and `gh` unlock remaining time).
- `config` (alias: `cfg`) `[unlock/default]`
- `options` (alias: `opts`) `[mixed]`
  - Show: `!c options`
  - Channel set (local only): `!c options set <key> <value>`
  - DM set with scope: `!c options set <key> <value> [local|global]`

Security:
- `unlock` (alias: `ul`) `[totp]` (`unlock ... status` is `[open]`)
- `lock` (alias: `lk`) `[mixed]` (`lock`/`lock status` are `[open]`; `lock extend ...` is `[totp]`)

Sessions:
- `start` (alias: `run`), `resume` (alias: `rs`), `choose` (alias: `pick`) `[unlock/default]`
  - `choose` accepts `continue|new|cancel` (`resume|replace` still supported as aliases).
- `use` (alias: `select`), `model` (alias: `mdl`), `models` (alias: `mdls`), `thread` (alias: `tid`), `reset`, `spec` (alias: `plan`) (`models` is `[open]`, others `[unlock/default]`)

Repo lifecycle:
- `create` (aliases: `createrepo`, `new`) `[totp]`
- `clone` (alias: `clonerepo`) `[totp]`
- `copy` (aliases: `copyrepo`, `cp`) `[totp]`

Run control:
- `stop`, `interrupt` (alias: `esc`), `kill`, `/quit`, `steer`, `answer` (alias: `reply`), `approve`, `deny`, `wait` `[unlock/default]`
- `!stop [session]` is a top-level shortcut for `interrupt` in mapped repo channels.
- `!pause [session]` is a top-level shortcut for `interrupt` in mapped repo channels.
- `!steer <text>` is a top-level shortcut for `steer` in mapped repo channels.
- `!s <text>` is a shorthand top-level shortcut for `steer` in mapped repo channels.
- `!s:<session> <text>` is a shorthand top-level shortcut for `steer <session> -- <text>` in mapped repo channels.
- `!a <text>` is a top-level shortcut for `answer` in mapped repo channels.
- `!a:<session> <text>` is a top-level shortcut for `answer <session> -- <text>` in mapped repo channels.
- `!y`/`!n` are top-level shortcuts for `approve`/`deny` in mapped repo channels.
- `!w` is a top-level shortcut for `wait` in mapped repo channels.
  - `wait` responses include `Related:` hints for quick follow-up (`!c answer`, `!a <text>`, `!ps`, `!c status`).

Repo helpers:
- `show` (aliases: `showrepo`, `tree`), `changes` (alias: `showchanges`) `[open]`
- `tests` (alias: `test`), `download` (alias: `dl`) `[unlock/default]`
- `git` `[unlock/default]`
  - Dangerous `git` helper operations (force push, branch delete) require opt-in and explicit confirmation token.
- `gh` `[unlock/gh]` (examples: `!c gh repo sync` or `!gh repo sync`)

Queue:
- `logs` (alias: `log`), `cancel` (alias: `drop`), `rerun` (alias: `retry`) `[unlock/default]`
- `!log [n]` is a top-level shortcut for `logs [n]` in mapped repo channels.
- `!retry` is a top-level shortcut for `rerun` in mapped repo channels.
- `ps` `[open]`
- `!ps` is a top-level shortcut for `ps` in mapped repo channels.
  - `ps` includes per-job timing fields: `queued`, `started`, and `ended` (UTC ISO timestamps).
  - `logs` includes per-entry `started` and `ended` timestamps.

Passthrough:
- Any other `!c` text is sent as a prompt to Codex.
- When Codex emits a question/approval prompt (`Codex asks: ...`), a plain reply in the same channel/DM is relayed to the active session input automatically (or use `!c answer ...` explicitly).

## DM admin commands (optional)
Enable with `discord.dm_admin_enabled: true`. `!c` command forms always work in DMs (Discord only), and top-level `!<command>` forms are also supported for DM commands (for example `!repos`, `!bind <repo>`, `!reset all`).
Repo names passed to DM commands are normalized to lowercase (for example, `ProbablyFine` becomes `probablyfine`).

- `!c help`
- `!c repos`
- `!c sessions`
- `!c status`
- `!c config`
- `!c updates`
- `!c create/new <name>` (legacy: `createrepo`)
- `!c clone <name> <url>` (legacy: `clonerepo`)
- `!c copy/cp <from> <to>` (legacy: `copyrepo`)
- `!c deleterepo/del <name>`
- `!c renamerepo/ren <from> <to>`
- `!c unlock/ul [gh|all] [status|ttl]`
- `!c lock/lk [gh|all]`

When `discord.totp_enabled: true`, TOTP is always required in DMs for:
- `!c unlock [gh|all] [ttl]`
- `!c unlock extend [gh|all] <ttl>`
- `!c lock extend [gh|all] <ttl>`
- `!c create <name>` / `!c createrepo <name>` / `!c new <name>`
- `!c clone <name> <url>` / `!c clonerepo <name> <url>`
- `!c copy <from> <to>` / `!c copyrepo <from> <to>` / `!c cp <from> <to>`
- `!c deleterepo <name>` / `!c delete <name>`
- `!c renamerepo <from> <to>` / `!c rename <from> <to>`
- DM upload flows (attachment submit and upload-path response)

TOTP is required in DMs for GitHub CLI unless gh scope is unlocked:
- `!c gh <args>`
- `!gh <args>` (shortcut form also works in DMs)

TOTP is required in DMs unless the DM is unlocked for:
- `!c bind <repo>`
- `!c use <repo>`
- `!c repo <repo> <prompt>`
- `!c unbind`
- `!c answer [session] -- <text>` / `!c answer <text>`
- `!c approve [session]`
- `!c deny [session]`
- Non-prefixed DM prompts when a repo is bound

TOTP is not required in DMs for:
- `!c help`
- `!c repos`
- `!c sessions`
- `!c status`
- `!c config`
- `!c updates`
- `!c unlock [gh|all] status`
- `!c lock [gh|all]`

When a repo is bound in DMs, a message without `!c` is treated as a prompt unless Codex is currently awaiting input (then it is relayed to the active session stdin).
Attachments in channels or bound DMs will prompt for a destination path before saving. Attachment filenames are normalized to a basename before write.

## Package layout
Core modules are now grouped by responsibility:

- `codebridge/routing/` — router orchestration, routing helpers, status/config formatting, reply helpers.
- `codebridge/commands/` — command parsing, registry/dispatch, help rendering, model-list parsing.
- `codebridge/sessions/` — session state persistence, active-process tracking, queue/coordinator lifecycle.
- `codebridge/services/` — file transfer, health endpoint, git bootstrap lifecycle helpers.
- `codebridge/handlers/` — command handlers that operate behind the router boundary.
- `codebridge/adapters/` — transport adapter implementations (Discord/Telegram, Slack scaffold).
- `codebridge/util/` — shared utility primitives.

Backward-compatible top-level module shims are retained (for example `codebridge/router.py`) and re-export from the new package layout.

## Troubleshooting
- No response: confirm Message Content intent is enabled and saved, and your user ID is allowlisted.
- Repo error: ensure channel name matches `codex-<repo>` and `<code_root>/<repo>/.git` exists. Repo names are normalized to lowercase.
- DM admin: enable `discord.dm_admin_enabled` and ensure `allowed_user_ids` includes you; optionally set `dm_admin_user_ids` for a separate admin allowlist.
- Security logs (`state.log_dir/bridge.log`): look for `security.totp_invalid`, `security.totp_replay`, `security.totp_locked`, `security.totp_unlock`, `security.totp_success`.
- Codex execution errors are also written as JSON lines to `state.log_dir/codex_errors.log` (contains args, return code, stderr tail, and retry notes).

## Docs
- Architecture diagram (Mermaid): `docs/architecture.mmd`
- Docker run guide: `DOCKER.md`
- Slack setup: `SLACK.md`
- Telegram setup: `TELEGRAM.md`
