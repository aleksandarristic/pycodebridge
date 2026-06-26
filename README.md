# Agentic Coding Bridge (Python)

Bridge transport channels (`code-<repo>`) to agentic coding sessions in local repos under `code_root`. One channel maps to one agent session with queueing, multi-session support, and run control.

Default backend: Codex. Additional supported backends: Claude Code and Gemini CLI, selectable per session.

## Features
- Map `#code-<repo>` to `<code_root>/<repo>` (must exist, be inside root, and contain `.git`).
  Repo identifiers are canonicalized to lowercase.
- Stream agent JSONL output to transports; strip control codes; flag prompts needing user input.
- Per-channel queue, multi-session support (max 3 per channel), run control (stop/interrupt/kill/quit).
- Per-session backend selection across supported agentic coding CLIs.
- **Multi-agent dispatch** — `@claude @codex @gemini` syntax routes a task to multiple agents,
  with Claude planning first and workers running in parallel on isolated git branches.
- Optional DM admin mode for owner-only repo management (Discord).
- Transport-agnostic router (`MessageEvent` + `ResponseSink`).

## Integrations
- Discord (supported): `DISCORD.md`

## Transport capabilities
Adapters declare capabilities for threads, replies, uploads, downloads, and typing. Router behavior is gated by these flags.
- Discord: threads ✅, replies ❌, uploads ✅, downloads ✅, typing ✅

## Setup
Prereqs:
- Python 3.14+ (3.13/3.12 fallback)
- Default backend CLI installed and signed in (binary on PATH or set `codex.binary`).
- Optional: Claude Code CLI or Gemini CLI installed and authenticated for `claude` / `gemini` sessions.
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
   - `CODEX_AUTH_HOST=/absolute/path/to/default-backend-auth-dir` (optional; defaults to `./.docker-codex-auth`)
   - `GH_CONFIG_HOST=/absolute/path/to/gh-config-dir` (optional; defaults to `./.docker-gh-config` in Compose)
   - `HOST_UID=$(id -u)` and `HOST_GID=$(id -g)` (required for Compose)
   - To reuse an existing default-backend login in Compose, set `CODEX_AUTH_HOST=$HOME/.codex`
   - If `STATE_DIR_HOST` is omitted, default is `./.docker-state`
3) Preflight only: `./run_docker.sh --check`
4) Run container: `./run_docker.sh`
5) First-time default-backend auth in Docker (if not already authenticated in mounted auth dir):
   - `docker exec -it pycodebridge codex login --device-auth`
6) Headless with Compose: `docker compose up -d --build`
7) Full Docker details: `DOCKER.md`
   - For Docker/Compose, prefer `codex.sandbox: danger-full-access`. `workspace-write` can fail inside containers when the default backend's inner sandbox path relies on `bwrap`/user namespaces.
8) One-shot update + redeploy:
   - Preflight only: `./update.sh --check`
   - Update current branch and redeploy: `./update.sh`
   - Update a specific branch and redeploy: `./update.sh main`
9) Optional health endpoint:
   - Set `runtime.health_bind` (example: `127.0.0.1:8080`; non-loopback binds require `runtime.health_allow_public: true`)
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
- `channel_name_regex` (default `^code-([A-Za-z0-9._-]+)$`) — maps channel to repo name.
- Discord repo channels must be private (`@everyone` cannot view); messages in non-private Discord channels are ignored.
- `allow_plain_prompts` (default `false`) — treat non-prefixed messages as prompts in matching channels.
- `dm_admin_enabled` (default `false`) — enable DM admin commands.
- `dm_admin_user_ids` (default empty) — allowlist for DM admin (falls back to `allowed_user_ids`).
- `totp.enabled` (default `false`) — require TOTP for protected commands on all platforms.
- `totp.secret_env` (default `DISCORD_TOTP_SECRET`) — env var containing Base32 TOTP secret.
- `totp.window` (default `1`) — accepted clock skew window in 30s steps.
- `totp.limiter.max_failures` (default `5`) — invalid/replayed TOTP attempts allowed before lockout (`0` disables lockout).
- `totp.limiter.failure_window_seconds` (default `300`) — rolling window used when counting failed attempts.
- `totp.limiter.cooldown_seconds` (default `300`) — lockout duration after too many failures (`0` disables lockout).
- `totp.command_groups.git` (default `true`) — enforce TOTP/default-unlock behavior for `git` commands.
- `totp.command_groups.gh` (default `true`) — enforce TOTP/gh-unlock behavior for `gh` commands.
- `totp.command_groups.high_risk` (default `true`) — enforce always-TOTP behavior for high-risk commands (unlock mutations, repo create/clone/copy/delete/rename, and lock extend).
- `totp.command_groups.file_transfer` (default `true`) — enforce TOTP for upload flows and default-unlock behavior for `download`; set `false` to allow uploads/downloads without TOTP while TOTP remains enabled for other command groups.
- Legacy flat keys (`totp_enabled`, `totp_secret_env`, `totp_window`, limiter knobs) are still accepted for backward compatibility.
- `max_discord_message_chars` (default `1800`) — outbound chunk size.

### `codex`
- `binary` (default `codex`) — path/name of the default backend CLI.
- `code_root` (required) — directory containing git repos.
- `sandbox` (default `workspace-write`) — default backend sandbox mode.
- `ask_for_approval` (default empty) — optional default backend approval policy (`untrusted|on-failure|on-request|never`).
- `network_access` (default `false`) — when `true` and sandbox is `workspace-write`, add `-c sandbox_workspace_write.network_access=true`.
- `json` (default `true`) — JSONL streaming output (required).
- `start_prompt` (default template) — prompt used for new sessions.
- `model` (default empty) — default model; override per session with `!c model`.
- `model_reasoning_effort` (default `minimal`) — default reasoning effort to keep token spend low; valid default-backend values are `minimal`/`low`/`medium`/`high`/`xhigh`, or override per session with `!c model [session] <id|default> [reasoning|default]` / `!c effort [session] <level|default>`. Use `default` to clear a session override. Empty = the backend's built-in default.
- `env` (default `{}`) — extra environment variables for the default backend.

Important: if the default backend cannot run `git push`, make sure network is enabled for the sandbox level you selected in the host backend config (`~/.codex/config.toml`). For `workspace-write`, include:

```toml
[sandbox_workspace_write]
network_access = true
```

### `claude`
- `binary` (default `claude`) — path/name of Claude Code CLI.
- `permission_mode` (default `default`) — Claude permission mode; `dangerously-skip-permissions` is passed through when configured.
- `model` (default empty) — default Claude model for Claude sessions.
- `effort` (default empty) — default Claude effort level; override per session with `!c effort`.
- `env` (default `{}`) — extra environment variables for Claude Code.

### `gemini`
- `binary` (default `gemini`) — path/name of Gemini CLI.
- `approval_mode` (default `yolo`) — Gemini approval mode (`default|auto_edit|yolo|plan`).
- `model` (default empty) — default Gemini model for Gemini sessions.
- `api_key_env` (default empty) — optional host env var name whose value the bridge injects into Gemini runs as `GEMINI_API_KEY`. Recommended when you want API-key auth without storing secrets in YAML. Example: `GEMINI_API_KEY` or a host-specific secret name like `PYCODEBRIDGE_GEMINI_KEY`.
- `env` (default `{}`) — extra environment variables for Gemini CLI.

### `agent`
- `default_backend` (default `codex`) — default backend for new sessions (`codex|claude|gemini`). Override per session with `!c agent`.

### `dm_assistant`
- `enabled` (default `false`) — enable the bridge assistant for allowed users in unbound DMs.
- `default_backend` (default empty) — backend for the assistant `dm` session; empty falls back to `agent.default_backend`.
- `model` (default empty) — model override for the assistant session.
- `effort` (default empty) — effort/reasoning override for the assistant session.
- `memory_dir` (default empty) — directory for per-user markdown memory files; empty uses `{state.data_dir}/dm-memory/`.
- `start_prompt` (default template) — assistant start prompt template. Supported variables include `{{REPO_PATH}}`, `{{CODE_ROOT}}`, `{{MEMORY_FILE}}`, and `{{USER_ID}}`.

### `state`
- `data_dir` (required) — directory for state.json and locks.
- `log_dir` (required) — directory for runtime logs (`bridge.log`, legacy `codex_errors.log`, unified `session_jsonl/` logs) and audit artifacts.
- `lock_timeout_seconds` (default `600`) — stale lock timeout.
- `conflict_ttl_seconds` (default `60`) — conflict prompt TTL.
- `session_idle_ttl_seconds` (default `14400`) — sessions idle longer than this require explicit `continue`, `compact`, or `new` before resuming. Set `0` to disable expiry.

### `runtime`
- `log_level` (default `info`) — `debug|info|warn|error`.
- `health_bind` (default empty) — optional health HTTP bind (`<host>:<port>` or `<port>`). Non-loopback hosts require `health_allow_public: true`.
- `health_allow_public` (default `false`) — allow the health endpoint to bind to non-loopback interfaces such as `0.0.0.0`.
- `health_path` (default `/healthz`) — health endpoint path.
- `run_heartbeat_seconds` (default `120`) — interval for "still running" status messages.
- `run_completion_min_seconds` (default `300`) — minimum run duration before posting completion summary.
- `show_reasoning_details` (default `true`) — include reasoning level text in status/pinned output and relay backend thinking blocks when available.
- `show_tool_calls` (default `true`) — relay backend tool-call labels when available.
- `output_flush_seconds` (default `0.4`) — idle window for batching streamed output into fewer transport sends; set `0` to disable coalescing.

### `audit`
- `redact` (default `false`) — redact secrets from audit logs, session JSONL logs, and agent error logs before writing.
- `redact_patterns` (default `[]`) — optional extra regex patterns to redact in addition to the built-in secret patterns.

### `transport`
- `adapter` (default `discord`) — transport adapter to use (`discord` only).

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

### `files`
- `max_upload_mb` (default `200`) — maximum size for a single uploaded file.
- `max_upload_total_mb` (default `200`) — maximum total size for one upload batch.
- `max_upload_count` (default `20`) — maximum number of files in one upload batch.

### `repo_bootstrap`
- `agents_template` (default empty) — optional AGENTS.md template for `!c create`.
- `spec_prompt` (default template) — prompt used by `!c spec`.
- Managed create/clone/copy operations also seed `.agent-env.local.md` as a
  gitignored local memory file with initial tool availability hints. The ignore
  rules for `.agent-env.local.md` and `.venv/` are written to
  `.git/info/exclude`, so project `.gitignore` is not modified.

### Prompt profiles and model defaults
- Routine coding/support tasks:
  - Model: `gpt-5.4`
  - Reasoning: `medium`
  - Keep the default start prompt minimal and repo-focused.
- Complex refactors/investigations:
  - Model: `gpt-5.5`
  - Reasoning: `high`
  - Use a richer `repo_bootstrap.spec_prompt` only when needed.
- Lightweight profile pattern:
  - Keep the default start prompt short.
  - Store longer, task-specific prompts in repo docs (for example `instructions/`) and reference them from commands/workflows instead of embedding large static text in every new session.

## Commands
Command inventory and taxonomy baseline: `docs/COMMAND_SURFACE.md`

Prefix default is `!c`. Channels should be named `code-<repo>`.
In mapped repo channels/threads, every registered command and alias also works as top-level `!<command>` / `!<alias>` (for example `!models`, `!model`, `!status`, `!cfg`, `!logs`).
Session scope model: one logical session per channel scope and one per thread scope. Channel scope uses `default`; thread scope uses the normalized thread name.
When `discord.totp.enabled: true`, use `!c unlock <totp> [ttl]` to unlock default commands for your account (`30m`, `1h`, `2h`; default `1h`).
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
- `!help` (equivalent to `!c help`)
- `!c status`
- `!c stats [session]`
- `!c budget [status]`
- `!c peek [session]`
- `!c updates`
- `!c agents`
- `!c models [session] [refresh|--refresh]`
- `!c efforts [session]`
- `!c branch`
- `!c show` (alias: `showrepo`)
- `!c changes` (alias: `showchanges`)
- `!c ps`
- `!c unlock [gh|all] status`
- `!c lock [gh|all]`
- `!c lock status [gh|all]`
- `!unlock ...`, `!ul ...`, `!lock ...` (equivalent top-level forms for `!c unlock ...` / `!c lock ...`)

TOTP always required (high-risk in channel; controlled by `discord.totp.command_groups.high_risk`):
- `!c unlock [gh|all] [ttl]`
- `!c unlock extend [gh|all] <ttl>`
- `!c lock extend [gh|all] <ttl>`
- `!c create` (aliases: `createrepo`, `new`)
- `!c clone <url>` (alias: `clonerepo`)
- `!c copy <newname>` (aliases: `copyrepo`, `cp`)
- High-risk git remote mutations: `!c git remote set-url ...`, `!c git remote add ...`, `!c git remote remove ...`, `!c git remote rename ...`, `!c git remote set-head ...`
- Upload flows (attachment submit and upload-path response; controlled by `discord.totp.command_groups.file_transfer`)

DM admin `!c reset all` also requires TOTP before the yes/no confirmation when TOTP is enabled.

TOTP required for GitHub CLI unless gh scope is unlocked (controlled by `discord.totp.command_groups.gh`):
- `!c gh <args>`
- `!c gh-create [--public]`
- `!gh <args>` (shortcut for `!c gh <args>`)

TOTP required unless the chat is unlocked:
- `!c start [session]`
- `!c resume [session] <prompt>`
- `!c choose [session] continue|new|compact`
- `!continue` / `!cont` (shortcut for `!c choose continue` when a conflict prompt is pending)
- `!new` (shortcut for `!c choose new` when a conflict prompt is pending)
- `!compact` / `!cpt` (shortcut for `!c choose compact` when a conflict prompt is pending)
- `!c use <session>` (alias `select`)
- `!c agent [session] <codex|claude|gemini> [model] [effort]`
- `!c model [session] <id|default> [reasoning|default]`
- `!c effort [session] <level|default>`
- `!c thread [session] <id>`
- `!c reset [session]`
- `!c clear`
- `!c purge [session]`
- `!c purge stale <ttl>`
- `!c spec [session]`
- `!c workflow [session] <inspect|fix|review|ship> [focus]`
- `!c stop [session]`
- `!c interrupt [session]` (aliases: `int`, `esc`, `escape`)
- `!c kill [session]`
- `!c /quit [session]`
- `!stop [session]` (equivalent to `!c stop [session]`; sends ESC then SIGINT)
- `!interrupt` / `!int` / `!esc` / `!escape` (equivalent to `!c interrupt`; sends ESC only)
- `!pause [session]` (alias for `stop`)
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
- `!c download <path>` / `!c dl <path>` sends a repo-relative file back as a Discord attachment. Directories, missing files, and paths outside the repo are rejected.
- Attach one or more files in a repo channel or bound DM, then reply with a
  repo-relative destination path to upload them.
- `!c logs [session] [n]`
- Shortcut: `!log [n]` (maps to `!c logs [n]`)
- `!c unpin`
- `!c git <status|log|branches|branch|show|diff|remote|fetch|pull|add|commit|push|merge>`
- Shortcut: `!git ...` (maps to `!c git ...`)
- Any other prompt-style `!c ...` command that is not in the read-only list

- `!c reset [session]` clears scoped session context/runtime. The next `start`/`resume` in that scope starts fresh.
- `!c clear` clears the current channel's `default` session escape-hatch style without resolving the repo or invoking an agent backend. It kills the tracked process when present, cancels queued work for that session, and removes the persisted session entry.
- `!c agent`, `!c model`, and `!c effort` with no args show the current effective backend/model/effort for the active session.
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
- `status` (alias: `st`), `stats` (alias: `usage`), `peek` (alias: `pk`), `updates` (aliases: `update`, `version`, `u`) `[open]`
- `budget [status] | budget set <channel|user|session|run> <soft> <hard> | budget clear [channel|user|session|run|all]` (alias: `budgets`) `[open]`
- Top-level command forms are available for all command names and aliases (`!<command>` / `!<alias>`).
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
  - `choose` accepts `continue|new|compact` (`resume|replace|summary` still supported as aliases).
  - Shortcut: `!continue` / `!cont` maps to `choose continue` while a conflict is pending.
  - Shortcut: `!new` maps to `choose new`; `!compact` / `!cpt` maps to `choose compact` (while a conflict is pending).
- `use` (alias: `select`), `agent`, `model` (alias: `mdl`), `effort` (alias: `eff`), `thread` (alias: `tid`), `reset`, `workflow` (alias: `wf`), `spec` (alias: `plan`) `[unlock/default]`
- `agents`, `models` (alias: `mdls`), `efforts` `[open]`
  - `workflow` expands built-in repo macros: `inspect`, `fix`, `review`, `ship`.
  - Example: `!c workflow inspect auth flow`
  - Example: `!c workflow fix failing tests`

Repo lifecycle:
- `create` (aliases: `createrepo`, `new`) `[totp]`
- `clone` (alias: `clonerepo`) `[totp]`
- `copy` (aliases: `copyrepo`, `cp`) `[totp]`

Run control:
- `stop` (alias: `pause`), `interrupt` (aliases: `int`, `esc`, `escape`), `kill`, `/quit`, `steer`, `answer` (alias: `reply`), `approve` (alias: `y`), `deny` (alias: `n`), `wait` (alias: `w`) `[unlock/default]`
- `stop` sends ESC then SIGINT; `interrupt` sends ESC only.
- `!stop [session]` is the top-level form for `stop` in mapped repo channels.
- `!pause [session]` is an alias of `stop`.
- `!steer <text>` is a top-level shortcut for `steer` in mapped repo channels.
- `!s <text>` is a shorthand top-level shortcut for `steer` in mapped repo channels.
- `!s:<session> <text>` is a shorthand top-level shortcut for `steer <session> -- <text>` in mapped repo channels.
- `!a <text>` is a top-level shortcut for `answer` in mapped repo channels.
- `!a:<session> <text>` is a top-level shortcut for `answer <session> -- <text>` in mapped repo channels.
- `!y`/`!n` are top-level shortcuts for `approve`/`deny` in mapped repo channels.
- `!w` is a top-level shortcut for `wait` in mapped repo channels.
  - `wait` responses include `Related:` hints for quick follow-up (`!c answer`, `!a <text>`, `!ps`, `!c status`).

Repo helpers:
- `show` (aliases: `showrepo`, `tree`), `changes` (alias: `showchanges`), `branch` `[open]`
- `tests` (alias: `test`) `[unlock/default]`
- `download` (alias: `dl`) `[unlock/default]` when `discord.totp.command_groups.file_transfer` is enabled
- `unpin` `[unlock/default]` — remove all but the most recent pin from the current channel.
- `git` `[unlock/default]`
  - Dangerous `git` helper operations (force push, branch delete) require opt-in and explicit confirmation token.
- `gh` `[unlock/gh]` (examples: `!c gh repo sync` or `!gh repo sync`)
- `gh-create [--public]` `[unlock/gh]` creates the GitHub repo if absent and wires `origin` for the current repo.

Queue:
- `logs` (alias: `log`), `cancel` (alias: `drop`), `rerun` (alias: `retry`) `[unlock/default]`
- `!log [n]` is a top-level shortcut for `logs [n]` in mapped repo channels.
- `!retry` is a top-level shortcut for `rerun` in mapped repo channels.
- `ps` `[open]`
- `!ps` is a top-level shortcut for `ps` in mapped repo channels.
  - `ps` includes per-job timing fields: `queued`, `started`, and `ended` (UTC ISO timestamps).
  - `logs` includes per-entry `started` and `ended` timestamps.

Passthrough:
- Any other `!c` text is sent as a prompt to the selected agent backend.
- When the agent emits a question/approval prompt, a plain reply in the same channel/DM is relayed to the active session input automatically (or use `!c answer ...` explicitly).

## DM admin commands (optional)
Enable with `discord.dm_admin_enabled: true`. `!c` command forms always work in DMs (Discord only), and top-level `!<command>` forms are also supported for DM commands (for example `!repos`, `!bind <repo>`, `!reset all`).
Repo names passed to DM commands are normalized to lowercase (for example, `ProbablyFine` becomes `probablyfine`).

- `!c help`
- `!c repos`
- `!c sessions`
- `!c status`
- `!c config`
- `!c updates`
- `!c unpin` (clear old pins across matching repo channels)
- `!c create/new <name>` (legacy: `createrepo`)
- `!c clone <name> <url>` (legacy: `clonerepo`)
- `!c copy/cp <from> <to>` (legacy: `copyrepo`)
- `!c deleterepo/del <name>`
- `!c renamerepo/ren <from> <to>`
- `!c unlock/ul [gh|all] [status|ttl]`
- `!c lock/lk [gh|all]`

When `discord.totp.enabled: true`, TOTP is always required in DMs for:
- `!c unlock [gh|all] [ttl]`
- `!c unlock extend [gh|all] <ttl>`
- `!c lock extend [gh|all] <ttl>`
- `!c create <name>` / `!c createrepo <name>` / `!c new <name>`
- `!c clone <name> <url>` / `!c clonerepo <name> <url>`
- `!c copy <from> <to>` / `!c copyrepo <from> <to>` / `!c cp <from> <to>`
- `!c deleterepo <name>` / `!c delete <name>`
- `!c renamerepo <from> <to>` / `!c rename <from> <to>`
- DM upload flows (attachment submit and upload-path response; controlled by `discord.totp.command_groups.file_transfer`)

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

When a repo is bound in DMs, a message without `!c` is treated as a prompt unless the selected agent is currently awaiting input (then it is relayed to the active session stdin).
Attachments in repo channels or bound DMs start an upload flow and prompt for a
repo-relative destination path before saving. For one file, reply with a file
path such as `docs/input.txt`; for multiple files, reply with a directory path
ending in `/`, such as `uploads/`. Attachment filenames are normalized to a
basename before write; upload batches are bounded by `files.max_upload_mb`,
`files.max_upload_total_mb`, and `files.max_upload_count`, then saved via
repo-local temporary files with symlink-safe finalization.

## DM assistant
Enable with `dm_assistant.enabled: true`. When an allowed user sends a DM with no bound repo, messages without a command go to the bridge assistant. Bound DMs keep the repo prompt behavior described above.

The assistant runs as session `dm` in the pycodebridge repo under `codex.code_root`. Its start prompt includes the pycodebridge repo path, key doc paths (`README.md`, `AGENTS.md`, `docs/`), managed repo names, active session summaries, and the user's memory file path. It reads docs on demand instead of bulk-loading the repo.

Session lifecycle matches normal sessions: the first message starts the assistant session, later messages resume it, and idle sessions use the same `continue` / `new` / `compact` conflict flow. Assistant prompts require the default unlock when TOTP is enabled.

Assistant controls in unbound DMs:
- `!c agent [codex|claude|gemini] [model] [effort]`
- `!c model <id|default>`
- `!c effort <level|default>`
- `!c status`
- `!c reset`
- `!c choose continue|new|compact`
- `!c logs [n]`

The assistant stores per-user memory as markdown in `dm_assistant.memory_dir` or `{state.data_dir}/dm-memory/`. The agent can update that file during a session using normal file tools.

## Package layout
Core modules are now grouped by responsibility:

- `codebridge/routing/` — router orchestration, routing helpers, status/config formatting, reply helpers.
- `codebridge/commands/` — command parsing, registry/dispatch, help rendering, model-list parsing.
- `codebridge/sessions/` — session state persistence, active-process tracking, queue/coordinator lifecycle.
- `codebridge/services/` — file transfer, health endpoint, git bootstrap lifecycle helpers.
- `codebridge/handlers/` — command handlers that operate behind the router boundary.
- `codebridge/adapters/` — transport adapter implementations (Discord).
- `codebridge/util/` — shared utility primitives.

Backward-compatible top-level module shims are retained (for example `codebridge/router.py`) and re-export from the new package layout.

## Concurrent session isolation (worktrees)

Without isolation, two sessions on the same repo share one working directory and can
clobber each other's in-progress changes. Enable `worktrees` to give each session its
own `git worktree` on a dedicated branch.

- **How it works** — on session start, `git worktree add -b session/<key>/<ts> <path>` creates an isolated checkout. The agent subprocess runs there. On exit the branch and directory are removed (or kept, depending on `cleanup_on_end`).
- **Branch names** — `session/<channel-slug>/<yyyymmdd-hhmmss>`, visible in `git branch -a`.
- **Worktree paths** — siblings of the repo by default (`myapp-wt-<key>/`), or under `base_dir` if set.
- **Cleanup modes**
  - `remove` (default) — delete the worktree on exit; clean and ephemeral.
  - `keep` — leave the branch and directory for manual inspection.
  - `pr` — (future) push branch and open a draft PR, then remove.
- **Startup pruning** — stale worktrees left by crashed sessions are pruned automatically via `git worktree prune` on each startup.
- **Concurrency cap** — `max_per_repo` (default `8`) refuses new sessions when too many worktrees already exist for a repo.

Enable in config:
```yaml
worktrees:
  enabled: true
  cleanup_on_end: remove  # remove | keep | pr
```

## Multi-agent dispatch

Dispatch routes a single message to one or more AI agents, each running in a git worktree
on a branch forked from a shared **task branch**. Requires `worktrees.enabled: true`.

**Before you dispatch** — make sure the repo has a GitHub remote if you plan to close
with `!c done --pr`. Use `!c gh-create` to create a private GitHub repo and wire
`origin`; add `--public` for a public repo. Existing `origin` remotes are left alone.

**Syntax** — prefix your prompt with `@agent` handles:

```
@codex implement OAuth2 login
@codex @gemini refactor the payment module
@claude @codex add rate limiting with Redis
```

**Patterns**

| Pattern | Trigger | Behaviour |
|---------|---------|-----------|
| Solo | `@codex <prompt>` | One agent, one branch |
| Fan-out | `@codex @gemini <prompt>` | Both run in parallel, separate branches |
| Orchestrated | `@claude @codex <prompt>` | Claude plans first, workers receive the plan |

**Branch layout**

```
task/<repo>/<yyyymmdd-hhmmss>          ← persists across dispatches in a session
  └─ task/<repo>/<ts>-<agent>-<id>     ← per-worker branch, created each dispatch
```

**Close the task when done**

```
!c done          # uses dispatch.close_mode from config (default: pr)
!c done --pr     # push branch + open a draft PR
!c done --merge  # merge into default branch and push
```

**Config**

```yaml
dispatch:
  output_mode: both    # per_agent | aggregate | both
  close_mode: pr       # pr | merge
```

Full reference: [`docs/dispatch.md`](docs/dispatch.md)
Examples: [`docs/examples/`](docs/examples/)

## State And Artifact Map
- `state.data_dir/state.json` — canonical persisted channel/session metadata, DM bindings, and runtime options.
- `state.data_dir/state.json.lock` — file lock used for atomic state mutations.
- `state.log_dir/session_jsonl/active/<channel>/repo-<repo>__session-<session>.jsonl` — primary per-session timeline log stream.
- `state.log_dir/session_jsonl/archive/<channel>/repo-<repo>__session-<session>-<timestamp>.tgz` — mandatory archive for active logs older than 30 days (kept indefinitely).
- `state.log_dir/<channel>/repo-<repo>__session-<session>/thread-<thread>/...` — detailed per-request audit artifacts (`*.request.json`, legacy `*.codex.jsonl`, `*.discord_out.txt`, legacy `*.codex.stderr.txt`).
- `state.log_dir/session_archives/<channel>/repo-<repo>__session-<session>/<archive-id>.txt` — optional session summary archives for lifecycle restore flows.

## Troubleshooting
- No response: confirm Message Content intent is enabled and saved, and your user ID is allowlisted.
- Repo error: ensure channel name matches `code-<repo>` and `<code_root>/<repo>/.git` exists. Repo names are normalized to lowercase.
- DM admin: enable `discord.dm_admin_enabled` and ensure `allowed_user_ids` includes you; optionally set `dm_admin_user_ids` for a separate admin allowlist.
- Security logs (`state.log_dir/bridge.log`): look for `security.totp_invalid`, `security.totp_replay`, `security.totp_locked`, `security.totp_unlock`, `security.totp_success`.
- Session timeline logs (first place to check): `state.log_dir/session_jsonl/active/<channel>/repo-<repo>__session-<session>.jsonl`.
  - Active session logs are retained for 30 days.
  - Logs older than 30 days are mandatorily archived to `state.log_dir/session_jsonl/archive/...` as `.tgz`.
  - Archived logs are kept indefinitely.
- Agent execution errors are also written as JSON lines to legacy `state.log_dir/codex_errors.log` (contains args, return code, stderr tail, and retry notes).

## Docs
- Architecture diagram (Mermaid): `docs/architecture.mmd`
- Docker run guide: `DOCKER.md`
- Multi-agent dispatch: `docs/dispatch.md`
  - Example: orchestrated `@claude @codex`: `docs/examples/login-feature.md`
  - Example: parallel fan-out `@codex @gemini`: `docs/examples/refactor.md`
  - Example: solo `@claude`: `docs/examples/solo-claude.md`
