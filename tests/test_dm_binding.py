import asyncio

from codebridge import config as cfgmod
from codebridge.handlers import dm_admin
from codebridge.state import Store
from codebridge.transport import Capabilities, MessageEvent


class _FakeSink:
    def __init__(self, channel_id: str) -> None:
        self.channel_id = channel_id
        self.sent = []

    async def send(self, content: str, thread_id: str | None = None, reply_to_id: str | None = None) -> None:
        _ = (thread_id, reply_to_id)
        self.sent.append(content)

    def capabilities(self) -> Capabilities:
        return Capabilities(threads=True, replies=True, uploads=True, downloads=True, typing=True)

    def typing(self):
        return _FakeAsyncContext()

    async def update_pinned_status(self, user_id: str, session: str, text: str) -> None:
        return None

    async def send_file(self, path: str, filename: str, thread_id: str | None = None, reply_to_id: str | None = None) -> None:
        _ = (path, filename, thread_id, reply_to_id)
        return None


class _FakeAsyncContext:
    async def __aenter__(self):
        return None

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeLogger:
    def info(self, name: str, extra=None):
        return None


class _FakeRouter:
    def __init__(self, cfg: cfgmod.Config, store: Store) -> None:
        self.cfg = cfg
        self.state = store
        self.last_resume = None
        self.logger = _FakeLogger()
        self.pending_handled = False

    def _transport_prefix(self, event: MessageEvent) -> str:
        if event.platform == "telegram":
            return self.cfg.telegram.prefix or "!c"
        return self.cfg.discord.prefix or "!c"

    def _transport_user_allowed(self, event: MessageEvent) -> bool:
        if event.platform == "telegram":
            return event.author_id in self.cfg.telegram.allowed_user_ids
        return event.author_id in self.cfg.discord.allowed_user_ids

    def _dm_admin_allowed(self, user_id: str) -> bool:
        return user_id in self.cfg.discord.allowed_user_ids

    def dm_binding_key(self, event: MessageEvent) -> str:
        return f"{event.platform}:{event.channel_id}"

    def get_dm_binding(self, event: MessageEvent) -> str:
        state = self.state.load()
        return state.dm_bindings.get(self.dm_binding_key(event), "")

    def set_dm_binding(self, event: MessageEvent, repo_name: str) -> None:
        key = self.dm_binding_key(event)
        self.state.update(lambda fs: fs.dm_bindings.__setitem__(key, repo_name))

    def clear_dm_binding(self, event: MessageEvent) -> None:
        key = self.dm_binding_key(event)
        self.state.update(lambda fs: fs.dm_bindings.pop(key, None))

    def current_session_for_user(self, user_id: str, channel_id: str) -> str:
        return "default"

    async def handle_resume(self, event, sink, repo_name, repo_path, session, prompt):
        self.last_resume = {
            "repo_name": repo_name,
            "repo_path": repo_path,
            "session": session,
            "prompt": prompt,
        }

    async def handle_pending_upload_response(self, event: MessageEvent, sink, repo_name: str) -> bool:
        if event.content == "uploads/":
            self.pending_handled = True
            return True
        return False

    def append_audit_output(self, entry, msg: str) -> None:
        return None

    def audit_start(self, channel_id: str, session: str, thread_id: str, meta):
        return None


def test_dm_binding_flow(tmp_path):
    cfg = cfgmod.Config()
    cfg.telegram.allowed_user_ids = ["user"]
    cfg.telegram.prefix = "!c"
    cfg.codex.code_root = str(tmp_path)
    cfg.state.data_dir = str(tmp_path / "state")
    cfg.state.log_dir = str(tmp_path / "logs")

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    store = Store(cfg.state.data_dir)
    router = _FakeRouter(cfg, store)
    sink = _FakeSink("dm-1")
    event = MessageEvent(
        platform="telegram",
        content="!c bind repo",
        channel_id="dm-1",
        channel_name="",
        author_id="user",
        author_is_bot=False,
        is_dm=True,
    )

    async def run():
        await dm_admin.handle_dm_message(router, event, sink)
        event_status = MessageEvent(
            platform="telegram",
            content="!c status",
            channel_id="dm-1",
            channel_name="",
            author_id="user",
            author_is_bot=False,
            is_dm=True,
        )
        await dm_admin.handle_dm_message(router, event_status, sink)
        event_unbind = MessageEvent(
            platform="telegram",
            content="!c unbind",
            channel_id="dm-1",
            channel_name="",
            author_id="user",
            author_is_bot=False,
            is_dm=True,
        )
        await dm_admin.handle_dm_message(router, event_unbind, sink)

    asyncio.run(run())

    assert sink.sent[0].startswith("Bound repo: repo")
    assert "Bound repo: repo" in sink.sent[1]
    assert sink.sent[2] == "Repo binding cleared."


def test_dm_binding_non_prefixed_prompt(tmp_path):
    cfg = cfgmod.Config()
    cfg.telegram.allowed_user_ids = ["user"]
    cfg.telegram.prefix = "!c"
    cfg.codex.code_root = str(tmp_path)
    cfg.state.data_dir = str(tmp_path / "state")
    cfg.state.log_dir = str(tmp_path / "logs")

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    store = Store(cfg.state.data_dir)
    router = _FakeRouter(cfg, store)
    sink = _FakeSink("dm-1")
    bind_event = MessageEvent(
        platform="telegram",
        content="!c bind repo",
        channel_id="dm-1",
        channel_name="",
        author_id="user",
        author_is_bot=False,
        is_dm=True,
    )
    prompt_event = MessageEvent(
        platform="telegram",
        content="fix tests",
        channel_id="dm-1",
        channel_name="",
        author_id="user",
        author_is_bot=False,
        is_dm=True,
    )

    async def run():
        await dm_admin.handle_dm_message(router, bind_event, sink)
        await dm_admin.handle_dm_message(router, prompt_event, sink)

    asyncio.run(run())

    assert router.last_resume is not None
    assert router.last_resume["repo_name"] == "repo"
    assert router.last_resume["prompt"] == "fix tests"


def test_dm_unbound_guidance(tmp_path):
    cfg = cfgmod.Config()
    cfg.telegram.allowed_user_ids = ["user"]
    cfg.telegram.prefix = "!c"
    cfg.codex.code_root = str(tmp_path)
    cfg.state.data_dir = str(tmp_path / "state")
    cfg.state.log_dir = str(tmp_path / "logs")

    store = Store(cfg.state.data_dir)
    router = _FakeRouter(cfg, store)
    sink = _FakeSink("dm-1")
    event = MessageEvent(
        platform="telegram",
        content="hello",
        channel_id="dm-1",
        channel_name="",
        author_id="user",
        author_is_bot=False,
        is_dm=True,
    )

    async def run():
        await dm_admin.handle_dm_message(router, event, sink)

    asyncio.run(run())

    assert "No repo bound" in sink.sent[0]


def test_dm_pending_upload_response_short_circuits(tmp_path):
    cfg = cfgmod.Config()
    cfg.telegram.allowed_user_ids = ["user"]
    cfg.telegram.prefix = "!c"
    cfg.codex.code_root = str(tmp_path)
    cfg.state.data_dir = str(tmp_path / "state")
    cfg.state.log_dir = str(tmp_path / "logs")

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    store = Store(cfg.state.data_dir)
    router = _FakeRouter(cfg, store)
    sink = _FakeSink("dm-1")
    bind_event = MessageEvent(
        platform="telegram",
        content="!c bind repo",
        channel_id="dm-1",
        channel_name="",
        author_id="user",
        author_is_bot=False,
        is_dm=True,
    )
    upload_response = MessageEvent(
        platform="telegram",
        content="uploads/",
        channel_id="dm-1",
        channel_name="",
        author_id="user",
        author_is_bot=False,
        is_dm=True,
    )

    async def run():
        await dm_admin.handle_dm_message(router, bind_event, sink)
        await dm_admin.handle_dm_message(router, upload_response, sink)

    asyncio.run(run())

    assert router.pending_handled is True
    assert router.last_resume is None
