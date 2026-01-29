import asyncio
from pathlib import Path

from codebridge.adapters.telegram import TelegramAdapter


class _FakeUser:
    def __init__(self, user_id: str, is_bot: bool = False) -> None:
        self.id = user_id
        self.is_bot = is_bot


class _FakeChat:
    def __init__(self, chat_id: str, title: str = "", chat_type: str = "private") -> None:
        self.id = chat_id
        self.title = title
        self.type = chat_type


class _FakeDocument:
    def __init__(self, file_id: str, file_name: str, file_size: int, mime_type: str) -> None:
        self.file_id = file_id
        self.file_name = file_name
        self.file_size = file_size
        self.mime_type = mime_type


class _FakePhoto:
    def __init__(self, file_id: str, file_size: int) -> None:
        self.file_id = file_id
        self.file_size = file_size


class _FakeMessage:
    def __init__(self, text: str, document, photos) -> None:
        self.text = text
        self.caption = ""
        self.message_id = 42
        self.message_thread_id = None
        self.document = document
        self.photo = photos
        self.video = None
        self.audio = None
        self.voice = None
        self.animation = None
        self.sticker = None


class _FakeUpdate:
    def __init__(self, message, chat, user) -> None:
        self.effective_message = message
        self.effective_chat = chat
        self.effective_user = user


class _FakeFile:
    def __init__(self, bot, file_id: str) -> None:
        self._bot = bot
        self._file_id = file_id

    async def download_to_drive(self, custom_path: str | None = None) -> None:
        self._bot.downloads.append((self._file_id, custom_path))


class _FakeBot:
    def __init__(self) -> None:
        self.requested = []
        self.downloads = []

    async def get_file(self, file_id: str) -> _FakeFile:
        self.requested.append(file_id)
        return _FakeFile(self, file_id)


def test_telegram_adapter_event_mapping_with_attachments(tmp_path: Path):
    adapter = TelegramAdapter()
    document = _FakeDocument("doc123", "notes.txt", 12, "text/plain")
    photos = [_FakePhoto("photo_small", 10), _FakePhoto("photo_big", 20)]
    message = _FakeMessage("", document, photos)
    update = _FakeUpdate(message, _FakeChat("chat", "codex-test"), _FakeUser("user"))
    bot = _FakeBot()

    event = adapter.event_from_update(update, bot)
    assert event.channel_id == "chat"
    assert event.channel_name == "codex-test"
    assert event.author_id == "user"
    assert event.is_dm is True
    assert event.message_id == "42"
    assert event.platform_thread_id == ""

    attachments = {att.filename: att for att in event.attachments}
    assert "notes.txt" in attachments
    photo_name = next(name for name in attachments if name.startswith("photo_photo_big"))
    assert attachments[photo_name].content_type == "image/jpeg"
    assert attachments[photo_name].size == 20

    async def run_save():
        await attachments["notes.txt"].save(str(tmp_path / "notes.txt"))

    asyncio.run(run_save())
    assert bot.requested == ["doc123"]
    assert bot.downloads == [("doc123", str(tmp_path / "notes.txt"))]
