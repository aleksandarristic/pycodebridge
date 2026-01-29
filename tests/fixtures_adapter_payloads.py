class FakeAuthor:
    def __init__(self, author_id: str, bot: bool = False) -> None:
        self.id = author_id
        self.bot = bot


class FakeGuild:
    def __init__(self, guild_id: str) -> None:
        self.id = guild_id


class FakeChannel:
    def __init__(self, channel_id: str, name: str = "") -> None:
        self.id = channel_id
        self.name = name


class FakeThread:
    def __init__(self, thread_id: str, name: str = "") -> None:
        self.id = thread_id
        self.name = name


class FakeUser:
    def __init__(self, user_id: str, is_bot: bool = False) -> None:
        self.id = user_id
        self.is_bot = is_bot


class FakeChat:
    def __init__(self, chat_id: str, title: str = "", chat_type: str = "private") -> None:
        self.id = chat_id
        self.title = title
        self.type = chat_type


class FakeMessage:
    def __init__(self, text: str, message_id: int, thread_id: int | None = None) -> None:
        self.text = text
        self.caption = ""
        self.message_id = message_id
        self.message_thread_id = thread_id
        self.document = None
        self.photo = []
        self.video = None
        self.audio = None
        self.voice = None
        self.animation = None
        self.sticker = None


class FakeUpdate:
    def __init__(self, message, chat, user) -> None:
        self.effective_message = message
        self.effective_chat = chat
        self.effective_user = user


class FakeBot:
    async def get_file(self, file_id: str):
        raise RuntimeError("not used in fixtures")
