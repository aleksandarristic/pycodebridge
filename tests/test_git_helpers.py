import asyncio

from codebridge import config as cfgmod
from codebridge.handlers import git_helpers


class _Sink:
    channel_id = "chan"


class _Router:
    def __init__(self) -> None:
        self.cfg = cfgmod.Config()
        self.cfg.discord.max_discord_message_chars = 1800
        self.messages: list[str] = []
        self.forbidden: list[str] = []

    async def reply(self, sink: _Sink, content: str) -> None:
        _ = sink
        self.messages.append(content)

    async def reply_forbidden(self, sink: _Sink, detail: str) -> None:
        _ = sink
        self.forbidden.append(detail)


def test_git_helper_blocks_dangerous_push_when_disabled(monkeypatch):
    async def run():
        router = _Router()
        sink = _Sink()

        async def _fake_run(repo_path: str, args: list[str], timeout: float = 30.0, env=None):
            _ = (repo_path, args, timeout, env)
            return "ok", None

        monkeypatch.setattr(git_helpers, "run_limited_command", _fake_run)
        await git_helpers.handle_git(router, sink, "/tmp/repo", "push --force")
        assert router.forbidden
        assert "Dangerous git operation blocked" in router.forbidden[0]

    asyncio.run(run())


def test_git_helper_requires_confirmation_for_dangerous_push(monkeypatch):
    async def run():
        router = _Router()
        sink = _Sink()
        router.cfg.git.allow_dangerous_ops = True
        router.cfg.git.require_confirmation_for_dangerous_ops = True
        router.cfg.git.dangerous_confirmation_token = "--confirm-dangerous"

        async def _fake_run(repo_path: str, args: list[str], timeout: float = 30.0, env=None):
            _ = (repo_path, args, timeout, env)
            return "ok", None

        monkeypatch.setattr(git_helpers, "run_limited_command", _fake_run)
        await git_helpers.handle_git(router, sink, "/tmp/repo", "push --force")
        assert router.forbidden
        assert "--confirm-dangerous" in router.forbidden[0]

    asyncio.run(run())


def test_git_helper_runs_dangerous_push_when_confirmed(monkeypatch):
    async def run():
        router = _Router()
        sink = _Sink()
        router.cfg.git.allow_dangerous_ops = True
        router.cfg.git.require_confirmation_for_dangerous_ops = True
        router.cfg.git.dangerous_confirmation_token = "--confirm-dangerous"
        seen: list[str] = []

        async def _fake_run(repo_path: str, args: list[str], timeout: float = 30.0, env=None):
            _ = (repo_path, timeout, env)
            seen.extend(args)
            return "ok", None

        monkeypatch.setattr(git_helpers, "run_limited_command", _fake_run)
        await git_helpers.handle_git(router, sink, "/tmp/repo", "push --force --confirm-dangerous")
        assert not router.forbidden
        assert seen[:2] == ["git", "push"]
        assert "--force" in seen
        assert "--confirm-dangerous" not in seen

    asyncio.run(run())


def test_git_helper_branch_delete_is_guarded(monkeypatch):
    async def run():
        router = _Router()
        sink = _Sink()

        async def _fake_run(repo_path: str, args: list[str], timeout: float = 30.0, env=None):
            _ = (repo_path, args, timeout, env)
            return "ok", None

        monkeypatch.setattr(git_helpers, "run_limited_command", _fake_run)
        await git_helpers.handle_git(router, sink, "/tmp/repo", "branch -D old")
        assert router.forbidden
        assert "local branch delete" in router.forbidden[0]

    asyncio.run(run())


def test_git_helper_add_routes_command(monkeypatch):
    async def run():
        router = _Router()
        sink = _Sink()
        seen: list[str] = []

        async def _fake_run(repo_path: str, args: list[str], timeout: float = 30.0, env=None):
            _ = (repo_path, timeout, env)
            seen.extend(args)
            return "ok", None

        monkeypatch.setattr(git_helpers, "run_limited_command", _fake_run)
        await git_helpers.handle_git(router, sink, "/tmp/repo", "add README.md")
        assert not router.forbidden
        assert seen == ["git", "add", "README.md"]

    asyncio.run(run())


def test_git_helper_fetch_routes_command(monkeypatch):
    async def run():
        router = _Router()
        sink = _Sink()
        seen: list[str] = []

        async def _fake_run(repo_path: str, args: list[str], timeout: float = 30.0, env=None):
            _ = (repo_path, timeout, env)
            seen.extend(args)
            return "ok", None

        monkeypatch.setattr(git_helpers, "run_limited_command", _fake_run)
        await git_helpers.handle_git(router, sink, "/tmp/repo", "fetch origin")
        assert not router.forbidden
        assert seen == ["git", "fetch", "origin"]

    asyncio.run(run())


def test_git_helper_unknown_subcommand_rejected(monkeypatch):
    async def run():
        router = _Router()
        sink = _Sink()

        async def _fake_run(repo_path: str, args: list[str], timeout: float = 30.0, env=None):
            _ = (repo_path, args, timeout, env)
            return "ok", None

        monkeypatch.setattr(git_helpers, "run_limited_command", _fake_run)
        await git_helpers.handle_git(router, sink, "/tmp/repo", "rebase main")
        assert router.forbidden == ["Unknown git subcommand."]

    asyncio.run(run())


def test_git_helper_reports_success_when_no_output(monkeypatch):
    async def run():
        router = _Router()
        sink = _Sink()

        async def _fake_run(repo_path: str, args: list[str], timeout: float = 30.0, env=None):
            _ = (repo_path, args, timeout, env)
            return "", None

        monkeypatch.setattr(git_helpers, "run_limited_command", _fake_run)
        await git_helpers.handle_git(router, sink, "/tmp/repo", "fetch")
        assert router.messages == ["git fetch completed successfully (no output)."]

    asyncio.run(run())


def test_branch_helper_reports_clean_branch(monkeypatch):
    async def run():
        router = _Router()
        sink = _Sink()
        seen: list[str] = []

        async def _fake_run(repo_path: str, args: list[str], timeout: float = 30.0, env=None):
            _ = (repo_path, timeout, env)
            seen.extend(args)
            return "## main...origin/main", None

        monkeypatch.setattr(git_helpers, "run_limited_command", _fake_run)
        await git_helpers.handle_branch(router, sink, "/tmp/repo")
        assert seen == ["git", "status", "--short", "--branch"]
        assert router.messages == ["Current branch: main\nWorking tree: clean"]

    asyncio.run(run())


def test_branch_helper_reports_dirty_branch(monkeypatch):
    async def run():
        router = _Router()
        sink = _Sink()

        async def _fake_run(repo_path: str, args: list[str], timeout: float = 30.0, env=None):
            _ = (repo_path, args, timeout, env)
            return "## feature/x\n M README.md\n?? notes.txt", None

        monkeypatch.setattr(git_helpers, "run_limited_command", _fake_run)
        await git_helpers.handle_branch(router, sink, "/tmp/repo")
        assert router.messages == ["Current branch: feature/x\nWorking tree: not clean"]

    asyncio.run(run())
