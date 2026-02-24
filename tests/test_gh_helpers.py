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


def test_gh_clone_completion_hint_for_repo_clone_with_slug():
    msg = _gh_clone_completion_hint(["repo", "clone", "owner/MyRepo"])
    assert msg == "Clone complete. Use `#codex-myrepo` for prompts."


def test_gh_clone_completion_hint_for_repo_clone_with_target_dir():
    msg = _gh_clone_completion_hint(["repo", "clone", "owner/repo", "LocalRepo"])
    assert msg == "Clone complete. Use `#codex-localrepo` for prompts."


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

    import asyncio

    asyncio.run(_run())
