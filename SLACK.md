# Slack setup

This document describes how to set up a Slack app/bot to work with this bridge.
The current Slack adapter is scaffold-only, so use this as planning guidance.

## 1) Create a Slack app
- Go to Slack API → “Create New App” → “From scratch”.
- Choose a workspace to install the app into.

## 2) Add bot permissions
Add OAuth scopes for the bot token (at minimum):
- `chat:write` (send messages)
- `channels:read` (read channel metadata)
- `channels:history` (read channel messages)
- `groups:history` (private channels if needed)
- `im:history` (DMs if needed)

Adjust scopes to match your intended usage.

## 3) Event delivery
You will need one of these:
- **Events API (recommended):** Configure a public HTTPS endpoint and subscribe to message events.
- **Socket Mode:** If you can’t expose a public endpoint, use Socket Mode with an app-level token.

## 4) Tokens and secrets
- **Bot token:** `xoxb-...`
- **Signing secret:** used to verify incoming requests
- **App-level token:** (Socket Mode only) `xapp-...`

## 5) Config placement (planned)
Slack adapter configuration will live under `transport` (plus Slack-specific fields), for example:
```
transport:
  adapter: "slack"
slack:
  bot_token: "xoxb-..."
  signing_secret: "..."
  app_token: "xapp-..."   # socket mode
  mode: "events"          # or "socket"
```

## 6) Notes
- Slack channels are not 1:1 with DMs; your adapter must handle channel, DM, and private channel events.
- Slack rate limits apply; expect retries and backoff.
