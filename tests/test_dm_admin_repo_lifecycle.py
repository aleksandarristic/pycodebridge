import asyncio

from codebridge import config as cfgmod
from codebridge.handlers import dm_admin
from codebridge.platform.transport import Capabilities, MessageEvent
from codebridge.routing.router import LOCAL_AGENT_ENV_FILENAME, LOCAL_AGENT_EXCLUDE_LINES, Router


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
    _agent_env_content = classmethod(Router._agent_env_content.__func__)
    _repo_tool_status = staticmethod(Router._repo_tool_status)
    _external_tool_status = staticmethod(Router._external_tool_status)
    _git_info_exclude_path = staticmethod(Router._git_info_exclude_path)
    _ensure_exclude_line = staticmethod(Router._ensure_exclude_line)

    def __init__(self, cfg: cfgmod.Config) -> None:
        self.cfg = cfg
        self.logger = _FakeLogger()
        self.bootstrapped: list[str] = []

    def append_audit_output(self, entry, msg: str) -> None:
        _ = (entry, msg)
        return None

    async def bootstrap_repo_git_config(self, repo_path: str) -> None:
        self.bootstrapped.append(repo_path)

    def bootstrap_agent_env_cache(self, repo_path: str) -> None:
        Router.bootstrap_agent_env_cache(self, repo_path)

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
        (tmp_path / "repo" / ".git").mkdir(parents=True, exist_ok=True)
        return "", None

    monkeypatch.setattr(dm_admin, "run_limited_command", _fake_run_limited_command)

    async def run():
        err = await dm_admin.dm_create_repo(router, event, sink, "repo", entry=None)
        assert err is None

    asyncio.run(run())
    assert router.bootstrapped == [str(tmp_path / "repo")]
    assert (tmp_path / "repo" / LOCAL_AGENT_ENV_FILENAME).exists()
    content = (tmp_path / "repo" / LOCAL_AGENT_ENV_FILENAME).read_text(encoding="utf-8")
    assert "`./.venv/bin/python`: missing" in content
    assert "Python virtualenv policy" in content
    assert "keep it gitignored" in content
    assert "`ruby`:" in content
    exclude = (tmp_path / "repo" / ".git" / "info" / "exclude").read_text(encoding="utf-8")
    for line in LOCAL_AGENT_EXCLUDE_LINES:
        assert line in exclude


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
    assert (tmp_path / "repo" / LOCAL_AGENT_ENV_FILENAME).exists()
    assert LOCAL_AGENT_ENV_FILENAME in (tmp_path / "repo" / ".git" / "info" / "exclude").read_text(encoding="utf-8")


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
        (tmp_path / "dst" / ".git").mkdir(parents=True, exist_ok=True)
        return "", None

    monkeypatch.setattr(dm_admin, "run_limited_command", _fake_run_limited_command)

    async def run():
        err = await dm_admin.dm_copy_repo(router, event, sink, "src", "dst", entry=None)
        assert err is None

    asyncio.run(run())
    assert router.bootstrapped == [str(tmp_path / "dst")]
    assert (tmp_path / "dst" / LOCAL_AGENT_ENV_FILENAME).exists()
    assert LOCAL_AGENT_ENV_FILENAME in (tmp_path / "dst" / ".git" / "info" / "exclude").read_text(encoding="utf-8")


def test_agent_env_bootstrap_preserves_existing_memory(tmp_path):
    cfg = cfgmod.Config()
    router = _FakeRouter(cfg)
    repo = tmp_path / "repo"
    (repo / ".git" / "info").mkdir(parents=True)
    env_path = repo / LOCAL_AGENT_ENV_FILENAME
    env_path.write_text("existing memory\n", encoding="utf-8")

    router.bootstrap_agent_env_cache(str(repo))
    router.bootstrap_agent_env_cache(str(repo))

    assert env_path.read_text(encoding="utf-8") == "existing memory\n"
    exclude_lines = (repo / ".git" / "info" / "exclude").read_text(encoding="utf-8").splitlines()
    for line in LOCAL_AGENT_EXCLUDE_LINES:
        assert exclude_lines.count(line) == 1
