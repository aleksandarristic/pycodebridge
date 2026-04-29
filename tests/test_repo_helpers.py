import asyncio

from codebridge.handlers import repo_helpers


def test_handle_showchanges_runs_git_calls_in_parallel(monkeypatch):
    started: list[str] = []
    gate = asyncio.Event()

    async def _fake_run_limited_command(repo_path, args, timeout=None, env=None):
        _ = (repo_path, timeout, env)
        started.append(" ".join(args))
        if len(started) == 2:
            gate.set()
        await gate.wait()
        if args[:3] == ["git", "status", "--short"]:
            return "## main...origin/main", None
        return " 1 file changed, 2 insertions(+)", None

    monkeypatch.setattr(repo_helpers, "run_limited_command", _fake_run_limited_command)

    class _Cfg:
        class discord:
            max_discord_message_chars = 4000

    class _Router:
        def __init__(self):
            self.cfg = _Cfg()
            self.replies = []

        async def reply(self, sink, text):
            _ = sink
            self.replies.append(text)

    class _Sink:
        pass

    router = _Router()

    async def run():
        await repo_helpers.handle_showchanges(router, _Sink(), "/tmp/repo")

    asyncio.run(run())
    assert len(started) == 2
    assert any(cmd.startswith("git status --short --branch") for cmd in started)
    assert any(cmd.startswith("git diff --stat") for cmd in started)
    assert any("main...origin/main" in msg for msg in router.replies)
