import asyncio
import json

from codebridge.handlers.system_helpers import _extract_line_version, _extract_version
from codebridge.handlers import system_helpers


def test_extract_version_finds_semver_in_codex_output():
    text = "WARNING: temp dir issue\ncodex-cli 0.101.0\n"
    assert _extract_version(text) == "0.101.0"


def test_extract_line_version_only_accepts_plain_semver_lines():
    text = "npm ERR! code EACCES\n9.2.0\n"
    assert _extract_line_version(text) == "9.2.0"
    assert _extract_line_version("npm ERR! something 9.2.0") == ""


def test_read_last_codex_error_summary(tmp_path):
    path = tmp_path / "codex_errors.log"
    path.write_text(
        "\n".join(
            [
                json.dumps({"return_code": 1, "note": "old", "stderr_tail": ["bad old"]}),
                json.dumps({"return_code": 2, "note": "latest", "stderr_tail": ["bad latest"]}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    summary = system_helpers._read_last_codex_error_summary(str(path))
    assert "rc=2" in summary
    assert "latest" in summary
    assert "bad latest" in summary


def test_handle_health_reports_expected_sections(tmp_path, monkeypatch):
    class _Ch:
        sessions = {"default": object()}

    class _State:
        channels = {"chan": _Ch()}

    class _Store:
        def load(self):
            return _State()

    class _Status:
        def __init__(self, status: str) -> None:
            self.status = status

    class _Coordinator:
        async def snapshot_all(self):
            return {"chan": [_Status("running"), _Status("queued")]}

    class _Cfg:
        class codex:
            code_root = ""

        class state:
            data_dir = ""
            log_dir = ""

    class _Runner:
        binary = "codex"

    class _Router:
        def __init__(self) -> None:
            self.runner = _Runner()
            self.coordinator = _Coordinator()
            self.state = _Store()
            self.cfg = _Cfg()
            self._codex_error_log_path = ""
            self.replies = []

        async def reply(self, sink, text):
            _ = sink
            self.replies.append(text)

    class _Sink:
        pass

    async def _fake_run_limited_command(repo_path, args, timeout, env=None):
        _ = (repo_path, args, timeout, env)
        return "codex 0.123.0", None

    monkeypatch.setattr(system_helpers, "run_limited_command", _fake_run_limited_command)

    router = _Router()
    sink = _Sink()

    async def run():
        await system_helpers.handle_health(router, sink, str(tmp_path))

    asyncio.run(run())
    text = "\n".join(router.replies)
    assert "Health:" in text
    assert "Codex version: 0.123.0" in text
    assert "Queue: 1 running, 1 queued" in text
    assert "Runtime uid:gid:" in text
    assert "Env sanity: code_root=missing, state_dir=missing, log_dir=missing" in text


def test_path_access_status_reports_ro_when_not_writable(tmp_path, monkeypatch):
    target = tmp_path / "root"
    target.mkdir()

    def _fake_access(path, mode):
        _ = mode
        return str(path) != str(target)

    monkeypatch.setattr(system_helpers.os, "access", _fake_access)

    assert system_helpers._path_access_status("") == "missing"
    assert system_helpers._path_access_status(str(tmp_path / "missing")) == "missing"
    assert system_helpers._path_access_status(str(target)) == "ok(ro)"


def test_handle_updates_runs_version_checks_in_parallel(tmp_path, monkeypatch):
    started: list[str] = []
    gate = asyncio.Event()

    class _Runner:
        binary = "codex"

    class _Router:
        def __init__(self):
            self.runner = _Runner()
            self.replies = []

        async def reply(self, sink, text):
            _ = sink
            self.replies.append(text)

    class _Sink:
        pass

    async def _fake_run_limited_command(repo_path, args, timeout, env=None):
        _ = (repo_path, timeout, env)
        started.append(" ".join(args))
        if len(started) == 2:
            gate.set()
        await gate.wait()
        if args[-1] == "--version":
            return "codex 0.1.0", None
        return "0.2.0\n", None

    monkeypatch.setattr(system_helpers, "run_limited_command", _fake_run_limited_command)
    router = _Router()

    async def run():
        await system_helpers.handle_updates(router, _Sink(), str(tmp_path))

    asyncio.run(run())
    assert len(started) == 2
    assert any(cmd.endswith(" --version") for cmd in started)
    assert any(cmd.startswith("npm view @openai/codex version") for cmd in started)
    assert any("update available (0.1.0 -> 0.2.0)" in msg for msg in router.replies)
