# Discord Bot Setup (Private)

This bot is meant for private use. Keep the token and invite URL secret; do not publish or share either.

## Prerequisites
- Discord account with Manage Server permission on the target server.
- Developer Mode enabled (User Settings -> Advanced -> Developer Mode) so IDs can be copied.
- Codex CLI installed and signed in on the host machine.

## Create the application and bot
1) In the Discord Developer Portal, create a New Application.
2) Under Bot, add a bot user. Toggle Public Bot OFF (invite-only). Save.
3) Still under Bot, enable the Message Content Intent (required to read `!c` commands). Save.

## Invite (no default link)
When Public Bot is off, the Default Authorization Link may be absent/disabled. Use an explicit OAuth URL instead:
- Get the Application (Client) ID from General Information.
- Use this URL (replace CLIENT_ID):
  `https://discord.com/oauth2/authorize?client_id=CLIENT_ID&scope=bot%20applications.commands&permissions=117760`
  - Permissions value 117760 corresponds to: View Channels, Send Messages, Embed Links, Attach Files, Read Message History.
- Open the URL while signed in to Discord and pick the server (requires Manage Server on that server).

If you prefer the UI: in OAuth2 -> URL Generator, check `bot` and `applications.commands`, then select the same permissions above to generate the link.

### Checkboxes (for clarity)
- Bot tab -> Privileged Gateway Intents: enable Message Content Intent (leave Presence/Server Members off unless needed).
- OAuth2 -> URL Generator: under Scopes, check bot and applications.commands. Under Bot Permissions, check:
  - View Channels
  - Send Messages
  - Embed Links
  - Attach Files
  - Read Message History
  - No other permissions are required (Manage Messages, Kick/Ban, etc. should stay off).

### DM admin mode
- If you enable DM admin commands (`discord.dm_admin_enabled: true`), no extra Discord permissions are needed beyond the list above.
- DM admin commands only work for allowlisted users; keep your bot private and avoid sharing the invite URL.

## DM admin troubleshooting
- Ensure `discord.dm_admin_enabled: true` in `config.yaml`.
- Confirm your user ID is listed in `discord.allowed_user_ids` or `discord.dm_admin_user_ids`.
- DM the bot directly (not a server channel) and use either `!c ...` or top-level `!...` command forms.
- Verify Message Content intent is enabled and saved in the Developer Portal.

## Channels and access
- Create private text channels named `codex-<repo>` (e.g., `codex-myservice`), matching repos under your configured `code_root`.
  Repo identifiers are normalized to lowercase, so prefer lowercase repo directory names.
- Ensure the bot's role can View Channels and Send Messages in those channels.
- The bot ignores messages in non-private Discord channels.

## Collect IDs for config
- User IDs (for allowlist): with Developer Mode on, right-click a user -> Copy ID. Add these to `discord.allowed_user_ids` (empty means nobody can use the bot).
- Guild (server) ID (required for strict lock): right-click the server name -> Copy Server ID. Set `discord.guild_id` to lock the bot to that server. With this set, the bot rejects messages from other guilds and auto-leaves them.

## Configure the bridge
1) Copy `config.example.yaml` to `config.yaml`.
2) Set `discord.allowed_user_ids` to your user ID(s) and set `discord.guild_id` to your server ID for strict guild lock.
3) Set `codex.code_root` to the absolute path that contains your git repos. Each `codex-<repo>` channel maps by lowercase repo id to `<code_root>/<repo>` with a `.git` directory.
   - Optional: set `codex.ask_for_approval` to one of `untrusted|on-failure|on-request|never` for explicit Codex permission behavior.
4) Adjust `state.data_dir`/`state.log_dir` to writable locations (defaults under your home are fine).
5) Set the bot token in `.env` (repo root):
   `DISCORD_TOKEN=YOUR_TOKEN`
   Keep this out of version control and env var managers that sync publicly.
6) Optional: enable DM admin with `discord.dm_admin_enabled: true` and add `discord.dm_admin_user_ids` if you want a separate allowlist for DMs.
7) Optional: enable TOTP for protected commands:
   - `discord.totp.enabled: true`
   - set `.env`: `DISCORD_TOTP_SECRET=BASE32_SECRET`
   - include codes in protected commands: `--totp 123456`
   - run `!c help` for categorized commands with auth tags: `[open]`, `[unlock/default]`, `[unlock/gh]`, `[totp]`, `[mixed]`
   - all registered channel commands support both `!c <command>` and top-level `!<command>` forms (including aliases)
   - short aliases are supported for common commands (examples: `status/st`, `updates/u`, `config/cfg`, `unlock/ul`, `lock/lk`, `create/new`, `copy/cp`, `download/dl`, `interrupt/int/esc/escape`, `approve/y`, `deny/n`, `wait/w`)
   - unlock command scopes for your account with a TTL:
     - `!c unlock <totp> [ttl]` for default scope (`30m`, `1h`, `2h`; default `1h`)
     - `!c unlock gh <totp> [ttl]` for GitHub CLI scope
     - `!c unlock all <totp> [ttl]` for both scopes
     - `!c unlock [gh|all] status` to check remaining time
     - `!c lock [gh|all]` to clear unlock scope(s) (`!c lock` clears all)
     - while default scope is unlocked, plain chat prompts are accepted even when `allow_plain_prompts` is `false`
   - limiter defaults: `totp.limiter.max_failures: 5`, `totp.limiter.failure_window_seconds: 300`, `totp.limiter.cooldown_seconds: 300`
   - lockout key is per user (`platform:user_id`); set `totp.limiter.max_failures: 0` to disable lockout
   - command-group toggles: `totp.command_groups.git`, `totp.command_groups.gh`, `totp.command_groups.high_risk`
   - Channel commands that do NOT require TOTP: `help`, `status`, `stats`, `peek`, `updates`, `models`, `show`/`showrepo`, `changes`/`showchanges`, `ps`, `unlock [gh|all] status`, `lock [gh|all]`
   - Channel commands that always require TOTP: `unlock [gh|all] [ttl]`, `create`/`createrepo`/`new`, `clone`/`clonerepo`, `copy`/`copyrepo`/`cp` (when `totp.command_groups.high_risk=true`)
   - `gh` requires TOTP unless `unlock gh` (or `unlock all`) is active (when `totp.command_groups.gh=true`)
   - Channel commands that require TOTP unless the channel is unlocked: `start`, `resume`, `choose`, `use/select`, `model`, `thread`, `spec`, `stop`, `kill`, `/quit`, `answer`, `approve`, `deny`, `cancel`, `rerun`, `config`, `tests`, `download`, `logs`, `git` (including `!git` shortcut), and plain prompts
   - Upload flows always require TOTP: attachment submit and upload-path response
   - DM commands that always require TOTP: `unlock [gh|all] [ttl]`, `create`/`createrepo`/`new`, `clone`/`clonerepo`, `copy`/`copyrepo`/`cp`, `deleterepo/delete/del`, `renamerepo/rename/ren`, and DM upload flows
   - `gh` in DMs requires TOTP unless `unlock gh` (or `unlock all`) is active
   - DM commands that require TOTP unless the DM is unlocked: `bind`, `use`, `repo`, `unbind`, `answer`, `approve`, `deny`, and bound non-prefixed prompts
   - DM commands that do NOT require TOTP: `help`, `repos`, `sessions`, `status`, `config`, `updates`, `unlock [gh|all] status`, `lock [gh|all]`

## Run
From the repo root:
`./.venv/bin/python -m cmd.bridge -config config.yaml`

In a `codex-<repo>` channel: send `!c config` to verify config, then `!c start`. If you get no response, re-check Message Content intent, token in `.env`, channel naming, and that the repo exists under `code_root`.

## Approval relay
- When Codex outputs `Codex asks: ...`, reply in plain text and the bridge relays it to the active session stdin.
- You can always reply explicitly with:
  - `!c answer <text>` (or `!c answer <session> -- <text>`)
  - `!c approve` (sends `yes`)
  - `!c deny` (sends `no`)

## File uploads/downloads
- Attach a file in a `codex-<repo>` channel and the bot will ask where to save it.
- Use `!c download <path>` to download a file from the repo.

## Capabilities
- Threads: supported (native Discord threads).
- Replies: not used; messages are sent directly to the channel/thread.
- Uploads/downloads: supported.
- Typing indicator: supported.

## Debug logs
- Runtime log: `state.log_dir/bridge.log`
- Codex execution error log (JSONL): `state.log_dir/codex_errors.log`
