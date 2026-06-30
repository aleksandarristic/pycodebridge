import asyncio
from pathlib import Path

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
    _agent_env_template_vars = classmethod(Router._agent_env_template_vars.__func__)
    _render_agent_env_template = classmethod(Router._render_agent_env_template.__func__)
    _render_agent_env_content = Router._render_agent_env_content
    _repo_tool_detail = classmethod(Router._repo_tool_detail.__func__)
    _repo_tool_status = staticmethod(Router._repo_tool_status)
    _external_tool_detail = classmethod(Router._external_tool_detail.__func__)
    _external_tool_status = staticmethod(Router._external_tool_status)
    _combined_tool_detail = classmethod(Router._combined_tool_detail.__func__)
    _gh_tool_detail = classmethod(Router._gh_tool_detail.__func__)
    _format_tool_detail = staticmethod(Router._format_tool_detail)
    _CommandResult = Router._CommandResult
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
        Router.seed_agents_template(self, repo_path)

    def ensure_agent_env_reference(self, repo_path: str) -> None:
        Router.ensure_agent_env_reference(self, repo_path)


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
    cfg.repo_bootstrap.agents_template = str(tmp_path / "AGENTS.sample.md")
    router = _FakeRouter(cfg)
    sink = _FakeSink()
    event = _dm_event()
    (tmp_path / "AGENTS.sample.md").write_text("# AGENTS\n\n## Intent\n- Test template\n", encoding="utf-8")

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
    assert "`./.venv/bin/ruff`:" in content
    assert "`ruby`:" in content
    agents = (tmp_path / "repo" / "AGENTS.md").read_text(encoding="utf-8")
    assert "## Intent" in agents
    assert LOCAL_AGENT_ENV_FILENAME in agents
    exclude = (tmp_path / "repo" / ".git" / "info" / "exclude").read_text(encoding="utf-8")
    for line in LOCAL_AGENT_EXCLUDE_LINES:
        assert line in exclude


def test_dm_clone_repo_applies_git_bootstrap(tmp_path, monkeypatch):
    cfg = cfgmod.Config()
    cfg.codex.code_root = str(tmp_path)
    cfg.repo_bootstrap.agents_template = str(tmp_path / "AGENTS.sample.md")
    router = _FakeRouter(cfg)
    sink = _FakeSink()
    event = _dm_event()
    (tmp_path / "AGENTS.sample.md").write_text("# AGENTS\n\n## Intent\n- Template clone\n", encoding="utf-8")

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
    agents = (tmp_path / "repo" / "AGENTS.md").read_text(encoding="utf-8")
    assert "## Intent" in agents
    assert LOCAL_AGENT_ENV_FILENAME in agents
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
    assert LOCAL_AGENT_ENV_FILENAME in (tmp_path / "dst" / "AGENTS.md").read_text(encoding="utf-8")
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


def test_agent_env_bootstrap_uses_common_exclude_for_linked_worktree(tmp_path):
    cfg = cfgmod.Config()
    router = _FakeRouter(cfg)
    repo = tmp_path / "repo"
    git_dir = tmp_path / "main.git" / "worktrees" / "repo"
    common_dir = tmp_path / "main.git"
    repo.mkdir()
    git_dir.mkdir(parents=True)
    (repo / ".git").write_text(f"gitdir: {git_dir}\n", encoding="utf-8")
    (git_dir / "commondir").write_text("../..\n", encoding="utf-8")

    router.bootstrap_agent_env_cache(str(repo))

    common_exclude = common_dir / "info" / "exclude"
    assert common_exclude.exists()
    exclude_lines = common_exclude.read_text(encoding="utf-8").splitlines()
    for line in LOCAL_AGENT_EXCLUDE_LINES:
        assert exclude_lines.count(line) == 1


def test_agent_env_bootstrap_uses_template_when_configured(tmp_path, monkeypatch):
    cfg = cfgmod.Config()
    template = tmp_path / ".agent-env.local.sample.md"
    template.write_text(
        "# Local Agent Environment\n\n- Last checked: {{CHECKED_DATE}}\n- python: {{PYTHON_STATUS}}\n- git: {{GIT_STATUS}}\n",
        encoding="utf-8",
    )
    cfg.repo_bootstrap.agent_env_template = str(template)
    router = _FakeRouter(cfg)
    repo = tmp_path / "repo"
    (repo / ".git" / "info").mkdir(parents=True)

    def fake_command_output(args):
        joined = " ".join(args)
        if "gh api user" in joined:
            return Router._CommandResult(ok=True, text="octocat")
        if "gh --version" in joined:
            return Router._CommandResult(ok=True, text="gh version 2.46.0")
        if "python3 --version" in joined:
            return Router._CommandResult(ok=True, text="Python 3.12.13")
        return Router._CommandResult(ok=True, text="tool 1.0.0")

    monkeypatch.setattr(_FakeRouter, "_command_output", classmethod(lambda cls, args: fake_command_output(args)), raising=False)
    router.bootstrap_agent_env_cache(str(repo))

    content = (repo / LOCAL_AGENT_ENV_FILENAME).read_text(encoding="utf-8")
    assert "{{CHECKED_DATE}}" not in content
    assert "python: missing" in content
    assert "git: available (`tool 1.0.0`)" in content


def test_agent_env_bootstrap_renders_rich_default_template(tmp_path, monkeypatch):
    cfg = cfgmod.Config()
    router = _FakeRouter(cfg)
    repo = tmp_path / "repo"
    (repo / ".git" / "info").mkdir(parents=True)
    venv_bin = repo / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    for name in ("python", "pip", "pytest", "ruff"):
        path = venv_bin / name
        path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        path.chmod(0o755)

    def fake_command_output(args):
        joined = " ".join(args)
        mapping = {
            ".venv/bin/python --version": "Python 3.12.13",
            ".venv/bin/pip --version": "pip 25.0.1",
            ".venv/bin/ruff --version": "ruff 0.5.0",
            "gh --version": "gh version 2.46.0",
            "gh api user --jq .login": "aleksandarristic",
            "git --version": "git version 2.47.3",
            "uv --version": "uv 0.11.25",
            "python3 --version": "Python 3.12.13",
        }
        for key, value in mapping.items():
            if key in joined:
                return Router._CommandResult(ok=True, text=value)
        return Router._CommandResult(ok=False, text="")

    monkeypatch.setattr(_FakeRouter, "_command_output", classmethod(lambda cls, args: fake_command_output(args)), raising=False)
    sample = (Path(__file__).resolve().parents[1] / ".agent-env.local.sample.md").read_text(encoding="utf-8")
    content = router._render_agent_env_template(sample, repo)
    assert "Treat it as an advisory cache only" in content
    assert "`./.venv/bin/python`: available (`Python 3.12.13`)" in content
    assert "`./.venv/bin/ruff`: available (`ruff 0.5.0`)" in content
    assert "`gh`: available (`gh version 2.46.0`) - authenticated as `aleksandarristic`" in content
    assert "`uv`: available (`uv 0.11.25`)" in content
    assert "## Worktrees and remote hygiene" in content
    assert "## Multi-agent dispatch" in content


def test_ensure_agent_env_reference_appends_to_existing_agents(tmp_path):
    cfg = cfgmod.Config()
    router = _FakeRouter(cfg)
    repo = tmp_path / "repo"
    repo.mkdir()
    agents = repo / "AGENTS.md"
    agents.write_text("# AGENTS\n\n## Intent\n- Existing\n", encoding="utf-8")

    router.ensure_agent_env_reference(str(repo))
    router.ensure_agent_env_reference(str(repo))

    content = agents.read_text(encoding="utf-8")
    assert content.count("## Local Environment") == 1
    assert LOCAL_AGENT_ENV_FILENAME in content
    assert "## Intent" in content
