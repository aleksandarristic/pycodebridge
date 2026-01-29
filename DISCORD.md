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
- DM the bot directly (not a server channel) and include the `!c` prefix.
- Verify Message Content intent is enabled and saved in the Developer Portal.

## Channels and access
- Create text channels named `codex-<repo>` (e.g., `codex-myservice`), matching repos under your configured `code_root`.
- Ensure the bot's role can View Channels and Send Messages in those channels.

## Collect IDs for config
- User IDs (for allowlist): with Developer Mode on, right-click a user -> Copy ID. Add these to `discord.allowed_user_ids` (empty means nobody can use the bot).
- Guild (server) ID (optional): right-click the server name -> Copy Server ID. Set `discord.guild_id` to lock the bot to that server.

## Configure the bridge
1) Copy `config.example.yaml` to `config.yaml`.
2) Set `discord.allowed_user_ids` to your user ID(s); set `discord.guild_id` if you want server lock-in.
3) Set `codex.code_root` to the absolute path that contains your git repos. Each `codex-<repo>` channel must map to `<code_root>/<repo>` with a `.git` directory.
4) Adjust `state.data_dir`/`state.log_dir` to writable locations (defaults under your home are fine).
5) Set the bot token in `.env` (repo root):
   `DISCORD_TOKEN=YOUR_TOKEN`
   Keep this out of version control and env var managers that sync publicly.
6) Optional: enable DM admin with `discord.dm_admin_enabled: true` and add `discord.dm_admin_user_ids` if you want a separate allowlist for DMs.

## Run
From the repo root:
`./.venv/bin/python -m cmd.bridge -config config.yaml`

In a `codex-<repo>` channel: send `!c config` to verify config, then `!c start`. If you get no response, re-check Message Content intent, token in `.env`, channel naming, and that the repo exists under `code_root`.

## File uploads/downloads
- Attach a file in a `codex-<repo>` channel and the bot will ask where to save it.
- Use `!c download <path>` to download a file from the repo.
