import discord

from .router import Router


class BridgeClient(discord.Client):
    def __init__(self, router: Router, **kwargs):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True
        intents.messages = True
        intents.dm_messages = True
        super().__init__(intents=intents, **kwargs)
        self.router = router

    async def on_ready(self) -> None:
        self.router.logger.info("discord.ready", extra={"user": str(self.user)})

    async def on_message(self, message: discord.Message) -> None:
        await self.router.handle_message(self, message)


def build_client(router: Router) -> BridgeClient:
    return BridgeClient(router)

