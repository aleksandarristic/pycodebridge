"""Telegram client adapter for the bridge."""

from __future__ import annotations

from typing import Optional

from telegram import Update
from telegram.ext import Application, ApplicationBuilder, ContextTypes, MessageHandler, filters

from .adapters.telegram import TelegramAdapter
from .router import Router


def build_application(router: Router, token: str) -> Application:
    """Construct a Telegram Application with handlers wired to the Router."""
    adapter = TelegramAdapter()

    async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        event = adapter.event_from_update(update)
        if not event.content:
            return
        sink = adapter.sink_for_chat(context.bot, event.channel_id)
        await router.handle_message(event, sink)

    app = ApplicationBuilder().token(token).build()
    app.add_handler(MessageHandler(filters.ALL, on_message))
    return app


async def run_polling(app: Application) -> None:
    """Run Telegram long polling until stopped."""
    await app.initialize()
    await app.start()
    try:
        if app.updater is None:
            raise RuntimeError("Telegram updater is not available for polling.")
        await app.updater.start_polling()
        await app.updater.idle()
    finally:
        await app.stop()
        await app.shutdown()
