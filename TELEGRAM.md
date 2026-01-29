# Telegram setup

This document describes how to set up a Telegram bot for this bridge.
The Telegram adapter is scaffold-only, so use this as planning guidance.

## 1) Create a bot with BotFather
1) Open Telegram and chat with `@BotFather`.
2) Run `/newbot` and follow prompts.
3) Copy the token provided by BotFather.

## 2) Choose update delivery
You have two typical options:
- **Webhook:** A public HTTPS endpoint where Telegram sends updates.
- **Long polling:** The bot periodically fetches updates (simpler to start).

## 3) Chat types and routing
Telegram does not have Discord-like “channels + DMs” semantics.
Instead, messages arrive from a **chat**, which can be:
- **Private chat**: 1:1 between the user and the bot.
- **Group chat**: a small group with the bot added.
- **Supergroup**: large groups with extra moderation features.

For this bridge, treat the Telegram **chat ID** as the channel identifier
(`MessageEvent.channel_id`) and map to repo names using the same `codex-<repo>`
convention in the message text (or via a per-chat config if you add it later).

## 4) Token placement (planned)
Telegram adapter configuration will live under `transport` (plus Telegram-specific fields), for example:
```
transport:
  adapter: "telegram"
telegram:
  bot_token: "123456:ABC-DEF..."
  mode: "polling"   # or "webhook"
  webhook_url: "https://..."
```

## 5) Notes
- Telegram uses chat IDs for routing instead of channels/threads.
- There is no native “typing” for bots, but you can send chat actions.
- Rate limits apply; handle retries and backoff.
