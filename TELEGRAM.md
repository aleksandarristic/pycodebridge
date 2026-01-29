# Telegram setup

This document describes how to set up a Telegram bot for this bridge.
The Telegram adapter uses long polling and expects chat titles to map to repos.

## 1) Create a bot with BotFather
1) Open Telegram and chat with `@BotFather`.
2) Run `/newbot` and follow prompts.
3) Copy the token provided by BotFather.

## 2) Choose update delivery
This bridge currently uses **long polling**. Webhooks are not wired yet.

## 3) Chat types and routing
Telegram does not have Discord-like “channels + DMs” semantics.
Instead, messages arrive from a **chat**, which can be:
- **Private chat**: 1:1 between the user and the bot.
- **Group chat**: a small group with the bot added.
- **Supergroup**: large groups with extra moderation features.

For this bridge, use **DMs** and bind a repo in each chat:
- `!c bind <repo>` to set the default repo for the DM
- `!c repo <repo> <prompt>` to run a one-off prompt
- `!c unbind` to clear the binding
When a repo is bound, any DM message without `!c` is treated as a prompt.
Attachments in bound DMs will prompt for a destination path before saving.

## 4) File uploads/downloads
- Attach a file in a bound DM or `codex-<repo>` group chat and the bot will ask where to save it.
- Use `!c download <path>` to download a file from the repo (sent as a document).
- Uploads respect `files.max_upload_mb` and Telegram's own file size limits.

## 5) Token placement
Telegram adapter configuration lives under `transport` and `telegram`, for example:
```
transport:
  adapter: "telegram"
telegram:
  token_env: "TELEGRAM_TOKEN"
  allowed_user_ids: ["1234567890"]
  prefix: "!c"
  channel_name_regex: "^codex-([A-Za-z0-9._-]+)$"
  allow_plain_prompts: false
```

## 6) Notes
- Telegram DMs use repo binding (`!c bind`) to select the repo context.
- Use `telegram.allowed_user_ids` to restrict access to your bot.
- There is no native “typing” for bots, but chat actions are supported.
- Rate limits apply; handle retries and backoff.
