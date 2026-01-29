from codebridge.adapters.discord import DiscordResponseSink
from codebridge.adapters.telegram import TelegramResponseSink
from codebridge.adapters.slack import SlackResponseSink
from codebridge.transport import Capabilities


class _FakeChannel:
    def __init__(self) -> None:
        self.id = "chan"

    async def send(self, content: str) -> None:
        return None

    def typing(self):
        return _FakeAsyncContext()


class _FakeAsyncContext:
    async def __aenter__(self):
        return None

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeBot:
    async def send_message(self, chat_id: str, text: str, **kwargs) -> None:
        return None

    async def send_document(self, chat_id: str, document, filename: str, **kwargs) -> None:
        return None

    async def send_chat_action(self, chat_id: str, action) -> None:
        return None


def test_discord_capabilities():
    sink = DiscordResponseSink(None, _FakeChannel())
    assert sink.capabilities() == Capabilities(threads=True, replies=False, uploads=True, downloads=True, typing=True)


def test_telegram_capabilities():
    sink = TelegramResponseSink(_FakeBot(), "chat")
    assert sink.capabilities() == Capabilities(threads=True, replies=True, uploads=True, downloads=True, typing=True)


def test_slack_capabilities_disabled():
    sink = SlackResponseSink("chan")
    assert sink.capabilities() == Capabilities()
