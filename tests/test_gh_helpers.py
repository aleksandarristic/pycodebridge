import asyncio

from codebridge.commands import registry as command_registry
from codebridge.handlers.gh_helpers import _gh_clone_completion_hint
from codebridge.handlers import gh_helpers
from codebridge import config as cfgmod


class _Sink:
    channel_id = "chan"


class _Router:
    def __init__(self) -> None:
        self.cfg = cfgmod.Config()
        self.cfg.discord.max_discord_message_chars = 1800
        self.messages: list[str] = []

    async def reply(self, sink: _Sink, content: str) -> None:
        _ = sink
        self.messages.append(content)

    async def reply_forbidden(self, sink: _Sink, content: str) -> None:
        _ = sink
        self.messages.append(content)


def test_gh_clone_completion_hint_for_repo_clone_with_slug():
    msg = _gh_clone_completion_hint(["repo", "clone", "owner/MyRepo"])
    assert msg == "Clone complete. Use `#code-myrepo` for prompts."


def test_gh_clone_completion_hint_for_repo_clone_with_target_dir():
    msg = _gh_clone_completion_hint(["repo", "clone", "owner/repo", "LocalRepo"])
    assert msg == "Clone complete. Use `#code-localrepo` for prompts."


def test_gh_clone_completion_hint_for_non_clone_command():
    assert _gh_clone_completion_hint(["pr", "status"]) == ""


def test_gh_helper_reports_success_when_no_output(monkeypatch):
    async def _run():
        router = _Router()
        sink = _Sink()

        async def _fake_run(repo_path: str, args: list[str], timeout: float = 30.0, env=None):
            _ = (repo_path, args, timeout, env)
            return "", None

        monkeypatch.setattr(gh_helpers, "run_limited_command", _fake_run)
        await gh_helpers.handle_gh(router, sink, "/tmp/repo", "repo sync")
        assert "gh command completed successfully (no output)." in router.messages

    asyncio.run(_run())


def test_gh_create_reports_existing_remote_without_gh_calls(monkeypatch):
    async def _run():
        router = _Router()
        sink = _Sink()
        calls: list[list[str]] = []

        async def _fake_run(repo_path: str, args: list[str], timeout: float = 30.0, env=None):
            _ = (repo_path, timeout, env)
            calls.append(args)
            if args == ["git", "rev-parse", "--is-inside-work-tree"]:
                return "true\n", None
            if args == ["git", "remote", "get-url", "origin"]:
                return "git@github.com:alice/repo.git\n", None
            raise AssertionError(f"unexpected command: {args}")

        monkeypatch.setattr(gh_helpers, "run_limited_command", _fake_run)
        await gh_helpers.handle_gh_create(router, sink, "repo", "/tmp/repo", "")

        assert router.messages == ["Remote already configured: git@github.com:alice/repo.git"]
        assert calls == [
            ["git", "rev-parse", "--is-inside-work-tree"],
            ["git", "remote", "get-url", "origin"],
        ]

    asyncio.run(_run())


def test_gh_create_wires_existing_github_repo(monkeypatch):
    async def _run():
        router = _Router()
        sink = _Sink()
        calls: list[list[str]] = []

        async def _fake_run(repo_path: str, args: list[str], timeout: float = 30.0, env=None):
            _ = (repo_path, timeout, env)
            calls.append(args)
            if args == ["git", "rev-parse", "--is-inside-work-tree"]:
                return "true\n", None
            if args == ["git", "remote", "get-url", "origin"]:
                return "error: No such remote 'origin'\n", RuntimeError("exit 2")
            if args == ["gh", "api", "user", "--jq", ".login"]:
                return "alice\n", None
            if args[:3] == ["gh", "repo", "view"]:
                return "git@github.com:alice/repo.git\n", None
            if args == ["git", "remote", "add", "origin", "git@github.com:alice/repo.git"]:
                return "", None
            if args == ["git", "fetch", "origin"]:
                return "", None
            raise AssertionError(f"unexpected command: {args}")

        monkeypatch.setattr(gh_helpers, "run_limited_command", _fake_run)
        await gh_helpers.handle_gh_create(router, sink, "repo", "/tmp/repo", "")

        assert router.messages == ["Remote wired to existing GitHub repo: git@github.com:alice/repo.git"]
        assert ["git", "remote", "add", "origin", "git@github.com:alice/repo.git"] in calls
        assert ["git", "fetch", "origin"] in calls

    asyncio.run(_run())


def test_gh_create_creates_new_github_repo(monkeypatch):
    async def _run():
        router = _Router()
        sink = _Sink()
        calls: list[list[str]] = []

        async def _fake_run(repo_path: str, args: list[str], timeout: float = 30.0, env=None):
            _ = (repo_path, timeout, env)
            calls.append(args)
            if args == ["git", "rev-parse", "--is-inside-work-tree"]:
                return "true\n", None
            if args == ["git", "remote", "get-url", "origin"]:
                return "error: No such remote 'origin'\n", RuntimeError("exit 2")
            if args == ["gh", "api", "user", "--jq", ".login"]:
                return "alice\n", None
            if args[:3] == ["gh", "repo", "view"]:
                return "not found\n", RuntimeError("exit 1")
            if args == ["git", "log", "--oneline", "-1"]:
                return "abc123 initial\n", None
            if args[:4] == ["gh", "repo", "create", "repo"]:
                return "created\n", None
            raise AssertionError(f"unexpected command: {args}")

        monkeypatch.setattr(gh_helpers, "run_limited_command", _fake_run)
        await gh_helpers.handle_gh_create(router, sink, "repo", "/tmp/repo", "--public")

        assert router.messages == ["GitHub repo created and remote wired."]
        assert [
            "gh",
            "repo",
            "create",
            "repo",
            "--public",
            "--source",
            ".",
            "--remote",
            "origin",
            "--push",
        ] in calls

    asyncio.run(_run())


def test_gh_create_command_requires_gh_unlock():
    registry, _ = command_registry.build_registry()
    assert registry["gh-create"].auth == command_registry.AUTH_UNLOCK_GH
