import asyncio

from codebridge import config as cfgmod
from codebridge.handlers import dm_admin
from codebridge.platform.transport import Capabilities, MessageEvent


class _FakeSink:
    def __init__(self) -> None:
        self.channel_id = "dm-1"
        self.sent: list[str] = []

    async def send(self, content: str, thread_id: str | None = None, reply_to_id: str | None = None) -> None:
        _ = (thread_id, reply_to_id)
        self.sent.append(content)

    def capabilities(self) -> Capabilities:
        return Capabilities(threads=True, replies=True, uploads=True, downloads=True, typing=True)

    def typing(self):
        return _FakeTyping()

    async def update_pinned_status(self, user_id: str, session: str, text: str) -> None:
        return None

    async def send_file(self, path: str, filename: str, thread_id: str | None = None, reply_to_id: str | None = None) -> None:
        _ = (path, filename, thread_id, reply_to_id)
        return None


class _FakeTyping:
    async def __aenter__(self):
        return None

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeLogger:
    def info(self, *args, **kwargs):
        return None


class _FakeRouter:
    def __init__(self, cfg: cfgmod.Config) -> None:
        self.cfg = cfg
        self.logger = _FakeLogger()
        self.bootstrapped: list[str] = []

    def append_audit_output(self, entry, msg: str) -> None:
        _ = (entry, msg)
        return None

    async def bootstrap_repo_git_config(self, repo_path: str) -> None:
        self.bootstrapped.append(repo_path)

    def seed_agents_template(self, repo_path: str) -> None:
        _ = repo_path
        return None


def _dm_event() -> MessageEvent:
    return MessageEvent(
        platform="discord",
        content="",
        channel_id="dm-1",
        channel_name="",
        author_id="user-1",
        author_is_bot=False,
        is_dm=True,
    )


def test_dm_create_repo_applies_git_bootstrap(tmp_path, monkeypatch):
    cfg = cfgmod.Config()
    cfg.codex.code_root = str(tmp_path)
    router = _FakeRouter(cfg)
    sink = _FakeSink()
    event = _dm_event()

    async def _fake_run_limited_command(repo_path, args, timeout=30.0, env=None):
        _ = (repo_path, args, timeout, env)
        return "", None

    monkeypatch.setattr(dm_admin, "run_limited_command", _fake_run_limited_command)

    async def run():
        err = await dm_admin.dm_create_repo(router, event, sink, "repo", entry=None)
        assert err is None

    asyncio.run(run())
    assert router.bootstrapped == [str(tmp_path / "repo")]


def test_dm_clone_repo_applies_git_bootstrap(tmp_path, monkeypatch):
    cfg = cfgmod.Config()
    cfg.codex.code_root = str(tmp_path)
    router = _FakeRouter(cfg)
    sink = _FakeSink()
    event = _dm_event()

    async def _fake_run_limited_command(repo_path, args, timeout=30.0, env=None):
        _ = (repo_path, args, timeout, env)
        (tmp_path / "repo").mkdir(exist_ok=True)
        (tmp_path / "repo" / ".git").mkdir(exist_ok=True)
        return "", None

    monkeypatch.setattr(dm_admin, "run_limited_command", _fake_run_limited_command)

    async def run():
        err = await dm_admin.dm_clone_repo(
            router,
            event,
            sink,
            "repo",
            "https://github.com/openai/codex.git",
            entry=None,
        )
        assert err is None

    asyncio.run(run())
    assert router.bootstrapped == [str(tmp_path / "repo")]


def test_dm_copy_repo_applies_git_bootstrap(tmp_path, monkeypatch):
    cfg = cfgmod.Config()
    cfg.codex.code_root = str(tmp_path)
    router = _FakeRouter(cfg)
    sink = _FakeSink()
    event = _dm_event()

    src = tmp_path / "src"
    src.mkdir()
    (src / ".git").mkdir()
    (src / "README.md").write_text("hello", encoding="utf-8")

    async def _fake_run_limited_command(repo_path, args, timeout=30.0, env=None):
        _ = (repo_path, args, timeout, env)
        return "", None

    monkeypatch.setattr(dm_admin, "run_limited_command", _fake_run_limited_command)

    async def run():
        err = await dm_admin.dm_copy_repo(router, event, sink, "src", "dst", entry=None)
        assert err is None

    asyncio.run(run())
    assert router.bootstrapped == [str(tmp_path / "dst")]
