import asyncio

from codebridge import config as cfgmod
from codebridge.handlers import dm_admin
from codebridge.sessions.state import Store
from codebridge.platform.transport import Capabilities, MessageEvent


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
        self.uploads_requested = False
        self.coordinator = _FakeCoordinator()
        self.last_gh = None
        self.last_answer = None
        self.last_updates = None
        self.reset_all_calls = 0
        self.pending_session = ""
        self.pending_ambiguous = False
        self._reset_all_confirm_until = {}

    def _transport_prefix(self, event: MessageEvent) -> str:
        _ = event
        return self.cfg.discord.prefix or "!c"

    def _transport_user_allowed(self, event: MessageEvent) -> bool:
        _ = event
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

    async def handle_upload_request(self, event: MessageEvent, sink, repo_name: str, repo_path: str) -> None:
        self.uploads_requested = True

    async def handle_pending_upload_response(
        self,
        event: MessageEvent,
        sink,
        repo_name: str,
        content_override: str | None = None,
    ) -> bool:
        _ = (sink, repo_name)
        content = event.content if content_override is None else content_override
        if content == "uploads/":
            self.pending_handled = True
            return True
        return False

    def _totp_enabled(self, event: MessageEvent) -> bool:
        _ = event
        return False

    def _totp_is_unlocked(self, event: MessageEvent, scope: str = "default") -> bool:
        _ = (event, scope)
        return False

    def _normalize_unlock_totp_syntax(self, cmdline: str) -> str:
        return cmdline

    def _shortcut_cmdline(self, content: str) -> str:
        raw = (content or "").strip()
        lower = raw.lower()
        if lower == "!gh" or lower.startswith("!gh "):
            return ("gh " + raw[3:].strip()).strip()
        if lower == "!help" or lower.startswith("!help "):
            return ("help " + raw[5:].strip()).strip()
        if lower == "!unlock" or lower.startswith("!unlock "):
            return ("unlock " + raw[7:].strip()).strip()
        if lower == "!ul" or lower.startswith("!ul "):
            return ("unlock " + raw[3:].strip()).strip()
        if lower == "!lock" or lower.startswith("!lock "):
            return ("lock " + raw[5:].strip()).strip()
        if lower == "!st":
            return "status"
        if lower == "!u":
            return "updates"
        if lower == "!health" or lower.startswith("!health "):
            return ("health " + raw[7:].strip()).strip()
        if lower == "!diag" or lower.startswith("!diag "):
            return ("health " + raw[5:].strip()).strip()
        return ""

    def _totp_required_for_command(self, event: MessageEvent, cmd: str, rest: str) -> bool:
        _ = (event, cmd, rest)
        return False

    async def require_totp(self, event: MessageEvent, sink, command_name: str, text: str):
        _ = (event, sink, command_name)
        return True, text

    def append_audit_output(self, entry, msg: str) -> None:
        return None

    def audit_start(self, channel_id: str, session: str, thread_id: str, meta):
        return None

    async def handle_gh(self, sink, repo_path: str, rest: str) -> None:
        self.last_gh = {"repo_path": repo_path, "rest": rest}
        await sink.send(f"gh@{repo_path}: {rest}")

    async def pending_input_session(self, event: MessageEvent) -> tuple[str, bool]:
        _ = event
        return self.pending_session, self.pending_ambiguous

    async def handle_answer(self, event: MessageEvent, sink, session: str, text: str) -> None:
        _ = (event, sink)
        self.last_answer = {"session": session, "text": text}

    async def handle_updates(self, sink, repo_path: str) -> None:
        self.last_updates = repo_path
        await sink.send(f"updates@{repo_path}")

    async def handle_health(self, sink, repo_path: str) -> None:
        await sink.send(f"health@{repo_path}")

    def begin_reset_all_confirmation(self, event: MessageEvent, ttl_seconds: int = 60) -> int:
        key = f"{event.platform}:{event.author_id}"
        self._reset_all_confirm_until[key] = ttl_seconds
        return ttl_seconds

    def consume_reset_all_confirmation(self, event: MessageEvent) -> bool:
        key = f"{event.platform}:{event.author_id}"
        if key not in self._reset_all_confirm_until:
            return False
        self._reset_all_confirm_until.pop(key, None)
        return True

    def has_reset_all_confirmation_pending(self, event: MessageEvent) -> bool:
        key = f"{event.platform}:{event.author_id}"
        return key in self._reset_all_confirm_until

    def clear_reset_all_confirmation(self, event: MessageEvent) -> None:
        key = f"{event.platform}:{event.author_id}"
        self._reset_all_confirm_until.pop(key, None)

    async def handle_reset_all_sessions(self, sink) -> None:
        self.reset_all_calls += 1
        await sink.send("Reset all sessions: cleared stored context for 0 session(s), killed 0 active process(es), cancelled 0 queued job(s).")


class _FakeCoordinator:
    async def snapshot_all(self):
        return {}


def test_dm_binding_flow(tmp_path):
    cfg = cfgmod.Config()
    cfg.discord.allowed_user_ids = ["user"]
    cfg.discord.prefix = "!c"
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
        platform="discord",
        content="!bind repo",
        channel_id="dm-1",
        channel_name="",
        author_id="user",
        author_is_bot=False,
        is_dm=True,
    )

    async def run():
        await dm_admin.handle_dm_message(router, event, sink)
        event_status = MessageEvent(
            platform="discord",
            content="!status",
            channel_id="dm-1",
            channel_name="",
            author_id="user",
            author_is_bot=False,
            is_dm=True,
        )
        await dm_admin.handle_dm_message(router, event_status, sink)
        event_unbind = MessageEvent(
            platform="discord",
            content="!unbind",
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
    cfg.discord.allowed_user_ids = ["user"]
    cfg.discord.prefix = "!c"
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
        platform="discord",
        content="!c bind repo",
        channel_id="dm-1",
        channel_name="",
        author_id="user",
        author_is_bot=False,
        is_dm=True,
    )
    prompt_event = MessageEvent(
        platform="discord",
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


def test_dm_binding_normalizes_repo_name(tmp_path):
    cfg = cfgmod.Config()
    cfg.discord.allowed_user_ids = ["user"]
    cfg.discord.prefix = "!c"
    cfg.codex.code_root = str(tmp_path)
    cfg.state.data_dir = str(tmp_path / "state")
    cfg.state.log_dir = str(tmp_path / "logs")

    repo = tmp_path / "probablyfine"
    repo.mkdir()
    (repo / ".git").mkdir()

    store = Store(cfg.state.data_dir)
    router = _FakeRouter(cfg, store)
    sink = _FakeSink("dm-1")
    bind_event = MessageEvent(
        platform="discord",
        content="!c bind ProbablyFine",
        channel_id="dm-1",
        channel_name="",
        author_id="user",
        author_is_bot=False,
        is_dm=True,
    )
    prompt_event = MessageEvent(
        platform="discord",
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

    assert sink.sent[0].startswith("Bound repo: probablyfine")
    assert router.last_resume is not None
    assert router.last_resume["repo_name"] == "probablyfine"
    assert router.last_resume["repo_path"] == str(repo)


def test_dm_unbound_guidance(tmp_path):
    cfg = cfgmod.Config()
    cfg.discord.allowed_user_ids = ["user"]
    cfg.discord.prefix = "!c"
    cfg.codex.code_root = str(tmp_path)
    cfg.state.data_dir = str(tmp_path / "state")
    cfg.state.log_dir = str(tmp_path / "logs")

    store = Store(cfg.state.data_dir)
    router = _FakeRouter(cfg, store)
    sink = _FakeSink("dm-1")
    event = MessageEvent(
        platform="discord",
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
    cfg.discord.allowed_user_ids = ["user"]
    cfg.discord.prefix = "!c"
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
        platform="discord",
        content="!c bind repo",
        channel_id="dm-1",
        channel_name="",
        author_id="user",
        author_is_bot=False,
        is_dm=True,
    )
    upload_response = MessageEvent(
        platform="discord",
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


def test_dm_gh_unbound_uses_code_root(tmp_path):
    cfg = cfgmod.Config()
    cfg.discord.allowed_user_ids = ["user"]
    cfg.discord.prefix = "!c"
    cfg.codex.code_root = str(tmp_path)
    cfg.state.data_dir = str(tmp_path / "state")
    cfg.state.log_dir = str(tmp_path / "logs")

    store = Store(cfg.state.data_dir)
    router = _FakeRouter(cfg, store)
    sink = _FakeSink("dm-1")
    event = MessageEvent(
        platform="discord",
        content="!c gh repo list --visibility private --limit 5",
        channel_id="dm-1",
        channel_name="",
        author_id="user",
        author_is_bot=False,
        is_dm=True,
    )

    async def run():
        await dm_admin.handle_dm_message(router, event, sink)

    asyncio.run(run())

    assert router.last_gh is not None
    assert router.last_gh["repo_path"] == str(tmp_path)
    assert router.last_gh["rest"] == "repo list --visibility private --limit 5"


def test_dm_bang_gh_unbound_uses_code_root(tmp_path):
    cfg = cfgmod.Config()
    cfg.discord.allowed_user_ids = ["user"]
    cfg.discord.prefix = "!c"
    cfg.codex.code_root = str(tmp_path)
    cfg.state.data_dir = str(tmp_path / "state")
    cfg.state.log_dir = str(tmp_path / "logs")

    store = Store(cfg.state.data_dir)
    router = _FakeRouter(cfg, store)
    sink = _FakeSink("dm-1")
    event = MessageEvent(
        platform="discord",
        content="!gh repo list --limit 3",
        channel_id="dm-1",
        channel_name="",
        author_id="user",
        author_is_bot=False,
        is_dm=True,
    )

    async def run():
        await dm_admin.handle_dm_message(router, event, sink)

    asyncio.run(run())

    assert router.last_gh is not None
    assert router.last_gh["repo_path"] == str(tmp_path)
    assert router.last_gh["rest"] == "repo list --limit 3"


def test_dm_gh_bound_uses_repo_path(tmp_path):
    cfg = cfgmod.Config()
    cfg.discord.allowed_user_ids = ["user"]
    cfg.discord.prefix = "!c"
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
        platform="discord",
        content="!c bind repo",
        channel_id="dm-1",
        channel_name="",
        author_id="user",
        author_is_bot=False,
        is_dm=True,
    )
    gh_event = MessageEvent(
        platform="discord",
        content="!c gh auth status",
        channel_id="dm-1",
        channel_name="",
        author_id="user",
        author_is_bot=False,
        is_dm=True,
    )

    async def run():
        await dm_admin.handle_dm_message(router, bind_event, sink)
        await dm_admin.handle_dm_message(router, gh_event, sink)

    asyncio.run(run())

    assert router.last_gh is not None
    assert router.last_gh["repo_path"] == str(repo)
    assert router.last_gh["rest"] == "auth status"


def test_dm_updates_uses_bound_repo_path(tmp_path):
    cfg = cfgmod.Config()
    cfg.discord.allowed_user_ids = ["user"]
    cfg.discord.prefix = "!c"
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
        platform="discord",
        content="!c bind repo",
        channel_id="dm-1",
        channel_name="",
        author_id="user",
        author_is_bot=False,
        is_dm=True,
    )
    updates_event = MessageEvent(
        platform="discord",
        content="!c updates",
        channel_id="dm-1",
        channel_name="",
        author_id="user",
        author_is_bot=False,
        is_dm=True,
    )

    async def run():
        await dm_admin.handle_dm_message(router, bind_event, sink)
        await dm_admin.handle_dm_message(router, updates_event, sink)

    asyncio.run(run())

    assert router.last_updates == str(repo)
    assert any(msg.startswith("updates@") for msg in sink.sent)


def test_dm_health_uses_bound_repo_path(tmp_path):
    cfg = cfgmod.Config()
    cfg.discord.allowed_user_ids = ["user"]
    cfg.discord.prefix = "!c"
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
        platform="discord",
        content="!c bind repo",
        channel_id="dm-1",
        channel_name="",
        author_id="user",
        author_is_bot=False,
        is_dm=True,
    )
    health_event = MessageEvent(
        platform="discord",
        content="!health",
        channel_id="dm-1",
        channel_name="",
        author_id="user",
        author_is_bot=False,
        is_dm=True,
    )

    async def run():
        await dm_admin.handle_dm_message(router, bind_event, sink)
        await dm_admin.handle_dm_message(router, health_event, sink)

    asyncio.run(run())
    assert any(msg.startswith("health@") for msg in sink.sent)


def test_dm_answer_command_relays_without_repo_binding(tmp_path):
    cfg = cfgmod.Config()
    cfg.discord.allowed_user_ids = ["user"]
    cfg.discord.prefix = "!c"
    cfg.codex.code_root = str(tmp_path)
    cfg.state.data_dir = str(tmp_path / "state")
    cfg.state.log_dir = str(tmp_path / "logs")

    store = Store(cfg.state.data_dir)
    router = _FakeRouter(cfg, store)
    sink = _FakeSink("dm-1")
    answer_event = MessageEvent(
        platform="discord",
        content="!c answer yes",
        channel_id="dm-1",
        channel_name="",
        author_id="user",
        author_is_bot=False,
        is_dm=True,
    )

    async def run():
        await dm_admin.handle_dm_message(router, answer_event, sink)

    asyncio.run(run())

    assert router.last_answer is not None
    assert router.last_answer["text"] == "yes"


def test_dm_unprefixed_relay_rejects_unauthorized_user(tmp_path):
    cfg = cfgmod.Config()
    cfg.discord.allowed_user_ids = ["allowed-user"]
    cfg.discord.prefix = "!c"
    cfg.codex.code_root = str(tmp_path)
    cfg.state.data_dir = str(tmp_path / "state")
    cfg.state.log_dir = str(tmp_path / "logs")

    store = Store(cfg.state.data_dir)
    router = _FakeRouter(cfg, store)
    router.pending_session = "default"
    sink = _FakeSink("dm-1")
    event = MessageEvent(
        platform="discord",
        content="yes",
        channel_id="dm-1",
        channel_name="",
        author_id="intruder",
        author_is_bot=False,
        is_dm=True,
    )

    async def run():
        await dm_admin.handle_dm_message(router, event, sink)

    asyncio.run(run())

    assert router.last_answer is None
    assert any("You are not allowed to use this bot." in msg for msg in sink.sent)


def test_dm_admin_reset_all_executes_for_discord_admin_after_yes_confirmation(tmp_path):
    cfg = cfgmod.Config()
    cfg.discord.prefix = "!c"
    cfg.discord.dm_admin_enabled = True
    cfg.discord.allowed_user_ids = ["user"]
    cfg.codex.code_root = str(tmp_path)
    cfg.state.data_dir = str(tmp_path / "state")
    cfg.state.log_dir = str(tmp_path / "logs")

    store = Store(cfg.state.data_dir)
    router = _FakeRouter(cfg, store)
    sink = _FakeSink("dm-1")
    event = MessageEvent(
        platform="discord",
        content="!reset all",
        channel_id="dm-1",
        channel_name="",
        author_id="user",
        author_is_bot=False,
        is_dm=True,
    )
    event_yes = MessageEvent(
        platform="discord",
        content="yes",
        channel_id="dm-1",
        channel_name="",
        author_id="user",
        author_is_bot=False,
        is_dm=True,
    )

    async def run():
        await dm_admin.handle_dm_message(router, event, sink)
        await dm_admin.handle_dm_message(router, event_yes, sink)

    asyncio.run(run())

    assert router.reset_all_calls == 1
    assert any("Are you sure you want to reset all sessions" in msg for msg in sink.sent)
    assert any("Reset all sessions:" in msg for msg in sink.sent)


def test_dm_prepare_content_translates_uncovered_top_level_shortcuts(tmp_path):
    cfg = cfgmod.Config()
    cfg.discord.prefix = "!c"
    cfg.codex.code_root = str(tmp_path)
    cfg.state.data_dir = str(tmp_path / "state")
    cfg.state.log_dir = str(tmp_path / "logs")
    store = Store(cfg.state.data_dir)
    router = _FakeRouter(cfg, store)
    sink = _FakeSink("dm-1")

    cases = [
        ("!repos", "!c repos"),
        ("!sessions", "!c sessions"),
        ("!status", "!c status"),
        ("!config", "!c config"),
        ("!updates", "!c updates"),
        ("!create demo", "!c create demo"),
        ("!new demo", "!c create demo"),
        ("!clone demo https://github.com/openai/codex.git", "!c clone demo https://github.com/openai/codex.git"),
        ("!copy from to", "!c copy from to"),
        ("!del demo", "!c deleterepo demo"),
        ("!rename from to", "!c renamerepo from to"),
        ("!reset all", "!c reset all"),
        ("!bind repo", "!c bind repo"),
        ("!use repo", "!c use repo"),
        ("!repo repo fix tests", "!c repo repo fix tests"),
        ("!unbind", "!c unbind"),
        ("!answer yes", "!c answer yes"),
        ("!approve", "!c approve"),
        ("!deny", "!c deny"),
        ("!lk status", "!c lock status"),
        ("!commands", "!c help"),
    ]

    async def run():
        for raw, expected in cases:
            event = MessageEvent(
                platform="discord",
                content=raw,
                channel_id="dm-1",
                channel_name="",
                author_id="user",
                author_is_bot=False,
                is_dm=True,
            )
            content, handled = await dm_admin._prepare_dm_content(router, event, sink, raw, "!c")
            assert handled is False
            assert content == expected

    asyncio.run(run())


def test_dm_admin_reset_all_requires_all_keyword(tmp_path):
    cfg = cfgmod.Config()
    cfg.discord.prefix = "!c"
    cfg.discord.dm_admin_enabled = True
    cfg.discord.allowed_user_ids = ["user"]
    cfg.codex.code_root = str(tmp_path)
    cfg.state.data_dir = str(tmp_path / "state")
    cfg.state.log_dir = str(tmp_path / "logs")

    store = Store(cfg.state.data_dir)
    router = _FakeRouter(cfg, store)
    sink = _FakeSink("dm-1")
    event = MessageEvent(
        platform="discord",
        content="!c reset",
        channel_id="dm-1",
        channel_name="",
        author_id="user",
        author_is_bot=False,
        is_dm=True,
    )

    async def run():
        await dm_admin.handle_dm_message(router, event, sink)

    asyncio.run(run())

    assert router.reset_all_calls == 0
    assert any("Usage: !c reset all" in msg for msg in sink.sent)


def test_dm_admin_reset_all_yes_requires_pending_confirmation(tmp_path):
    cfg = cfgmod.Config()
    cfg.discord.prefix = "!c"
    cfg.discord.dm_admin_enabled = True
    cfg.discord.allowed_user_ids = ["user"]
    cfg.codex.code_root = str(tmp_path)
    cfg.state.data_dir = str(tmp_path / "state")
    cfg.state.log_dir = str(tmp_path / "logs")

    store = Store(cfg.state.data_dir)
    router = _FakeRouter(cfg, store)
    sink = _FakeSink("dm-1")
    event = MessageEvent(
        platform="discord",
        content="yes",
        channel_id="dm-1",
        channel_name="",
        author_id="user",
        author_is_bot=False,
        is_dm=True,
    )

    async def run():
        await dm_admin.handle_dm_message(router, event, sink)

    asyncio.run(run())

    assert router.reset_all_calls == 0
    assert any("No repo bound." in msg or "DM Repo Binding:" in msg for msg in sink.sent)


def test_dm_admin_reset_all_non_yes_reply_cancels(tmp_path):
    cfg = cfgmod.Config()
    cfg.discord.prefix = "!c"
    cfg.discord.dm_admin_enabled = True
    cfg.discord.allowed_user_ids = ["user"]
    cfg.codex.code_root = str(tmp_path)
    cfg.state.data_dir = str(tmp_path / "state")
    cfg.state.log_dir = str(tmp_path / "logs")

    store = Store(cfg.state.data_dir)
    router = _FakeRouter(cfg, store)
    sink = _FakeSink("dm-1")
    event = MessageEvent(
        platform="discord",
        content="!c reset all",
        channel_id="dm-1",
        channel_name="",
        author_id="user",
        author_is_bot=False,
        is_dm=True,
    )
    event_cancel = MessageEvent(
        platform="discord",
        content="no",
        channel_id="dm-1",
        channel_name="",
        author_id="user",
        author_is_bot=False,
        is_dm=True,
    )

    async def run():
        await dm_admin.handle_dm_message(router, event, sink)
        await dm_admin.handle_dm_message(router, event_cancel, sink)

    asyncio.run(run())

    assert router.reset_all_calls == 0
    assert any("Reset-all operation cancelled." in msg for msg in sink.sent)


def test_dm_admin_reset_all_rejected_for_non_admin(tmp_path):
    cfg = cfgmod.Config()
    cfg.discord.prefix = "!c"
    cfg.discord.dm_admin_enabled = True
    cfg.discord.allowed_user_ids = ["someone-else"]
    cfg.codex.code_root = str(tmp_path)
    cfg.state.data_dir = str(tmp_path / "state")
    cfg.state.log_dir = str(tmp_path / "logs")

    store = Store(cfg.state.data_dir)
    router = _FakeRouter(cfg, store)
    sink = _FakeSink("dm-1")
    event = MessageEvent(
        platform="discord",
        content="!c reset all",
        channel_id="dm-1",
        channel_name="",
        author_id="user",
        author_is_bot=False,
        is_dm=True,
    )

    async def run():
        await dm_admin.handle_dm_message(router, event, sink)

    asyncio.run(run())

    assert router.reset_all_calls == 0
    assert any("You are not allowed to use DM admin commands." in msg for msg in sink.sent)


def test_dm_prefixed_sink_adds_repo_prefix():
    sink = _FakeSink("dm-1")
    prefixed = dm_admin._PrefixedSink(sink, "repo")

    async def run():
        await prefixed.send("hello")

    asyncio.run(run())

    assert sink.sent == ["[repo] hello"]


def test_dm_admin_deleterepo_requires_dangerous_confirmation(tmp_path):
    cfg = cfgmod.Config()
    cfg.discord.prefix = "!c"
    cfg.discord.dm_admin_enabled = True
    cfg.discord.allowed_user_ids = ["user"]
    cfg.codex.code_root = str(tmp_path)
    cfg.state.data_dir = str(tmp_path / "state")
    cfg.state.log_dir = str(tmp_path / "logs")

    store = Store(cfg.state.data_dir)
    router = _FakeRouter(cfg, store)
    sink = _FakeSink("dm-1")
    event = MessageEvent(
        platform="discord",
        content="!c deleterepo repo",
        channel_id="dm-1",
        channel_name="",
        author_id="user",
        author_is_bot=False,
        is_dm=True,
    )

    async def run():
        await dm_admin.handle_dm_message(router, event, sink)

    asyncio.run(run())
    assert any("Dangerous operation detected (delete repo)." in msg for msg in sink.sent)
