import asyncio
import itertools
import os
import shutil
import subprocess
import sys

import pytest

from codebridge.codex import Options, Runner, _toml_string, display_texts, parse_event


def test_parse_event_agent_message():
    line = '{"type":"item.completed","item":{"type":"agent_message","text":"hi"}}'
    evt = parse_event(line)
    assert evt is not None
    texts = display_texts(evt)
    assert texts == ["hi"]


def test_parse_event_error_message():
    line = '{"type":"error","error":{"message":"bad"}}'
    evt = parse_event(line)
    texts = display_texts(evt)
    assert "bad" in texts


def test_runner_build_args_include_approval_policy():
    runner = Runner("codex", "workspace-write", {}, "on-request")
    args = runner.build_start_args("/tmp/repo", "hello", "", "")
    assert args[:4] == ["exec", "--json", "--cd", "/tmp/repo"]
    assert "--sandbox" in args
    assert "workspace-write" in args
    assert 'approval_policy="on-request"' in args
    assert "exec" in args


def test_runner_build_start_args_order_contract():
    runner = Runner("codex", "workspace-write", {}, "on-request", network_access=True)
    args = runner.build_start_args("/tmp/repo", "hello", "", "")
    assert args == [
        "exec",
        "--json",
        "--cd",
        "/tmp/repo",
        "--sandbox",
        "workspace-write",
        "-c",
        'approval_policy="on-request"',
        "-c",
        "sandbox_workspace_write.network_access=true",
        "hello",
    ]


def test_runner_build_resume_args_order_contract():
    runner = Runner("codex", "workspace-write", {}, "on-request", network_access=True)
    args = runner.build_resume_args("/tmp/repo", "thread_123", "fix it", "gpt-5", "high")
    assert args == [
        "exec",
        "--json",
        "--cd",
        "/tmp/repo",
        "--sandbox",
        "workspace-write",
        "-c",
        'approval_policy="on-request"',
        "-c",
        "sandbox_workspace_write.network_access=true",
        "resume",
        "thread_123",
        "--model",
        "gpt-5",
        "-c",
        'model_reasoning_effort="high"',
        "fix it",
    ]


def test_runner_build_resume_last_args_order_contract():
    runner = Runner("codex", "workspace-write", {}, "on-request", network_access=True)
    args = runner.build_resume_last_args("/tmp/repo", "continue", "gpt-5", "medium")
    assert args == [
        "exec",
        "--json",
        "--cd",
        "/tmp/repo",
        "--sandbox",
        "workspace-write",
        "-c",
        'approval_policy="on-request"',
        "-c",
        "sandbox_workspace_write.network_access=true",
        "resume",
        "--last",
        "--model",
        "gpt-5",
        "-c",
        'model_reasoning_effort="medium"',
        "continue",
    ]


@pytest.mark.parametrize(
    "variant,model,reasoning,approval,network",
    [
        ("start", "", "", "", False),
        ("start", "gpt-5", "", "on-request", False),
        ("start", "gpt-5", "high", "on-request", True),
        ("resume", "", "", "", False),
        ("resume", "gpt-5", "high", "on-request", True),
        ("resume_last", "", "medium", "never", True),
        ("resume_last", "gpt-5", "", "", False),
    ],
)
def test_runner_build_args_relative_order_matrix(variant, model, reasoning, approval, network):
    runner = Runner("codex", "workspace-write", {}, approval, network_access=network)
    repo = "/tmp/repo"
    prompt = "do work"
    if variant == "start":
        args = runner.build_start_args(repo, prompt, model, reasoning)
    elif variant == "resume":
        args = runner.build_resume_args(repo, "thread_123", prompt, model, reasoning)
    else:
        args = runner.build_resume_last_args(repo, prompt, model, reasoning)

    assert args[0:4] == ["exec", "--json", "--cd", repo]
    assert "--sandbox" in args
    sandbox_idx = args.index("--sandbox")
    assert args[sandbox_idx + 1] == "workspace-write"

    if approval:
        approval_idx = args.index("-c")
        assert args[approval_idx + 1].startswith("approval_policy=")
    if network:
        assert "sandbox_workspace_write.network_access=true" in args
    else:
        assert "sandbox_workspace_write.network_access=true" not in args

    if variant == "resume":
        resume_idx = args.index("resume")
        assert args[resume_idx + 1] == "thread_123"
    elif variant == "resume_last":
        resume_idx = args.index("resume")
        assert args[resume_idx + 1] == "--last"
    else:
        assert "resume" not in args

    if model:
        model_idx = args.index("--model")
        assert args[model_idx + 1] == model
    else:
        assert "--model" not in args

    if reasoning:
        assert any(str(token).startswith('model_reasoning_effort=') for token in args)
    else:
        assert not any(str(token).startswith('model_reasoning_effort=') for token in args)

    assert args[-1] == prompt


def test_runner_build_args_include_workspace_network_override_when_enabled():
    runner = Runner("codex", "workspace-write", {}, "on-request", network_access=True)
    args = runner.build_start_args("/tmp/repo", "hello", "", "")
    assert "sandbox_workspace_write.network_access=true" in args


def test_runner_build_args_skip_workspace_network_override_when_not_workspace_write():
    runner = Runner("codex", "read-only", {}, "on-request", network_access=True)
    args = runner.build_start_args("/tmp/repo", "hello", "", "")
    assert "sandbox_workspace_write.network_access=true" not in args


def test_runner_presents_tty_stdin_on_posix(tmp_path):
    if os.name == "nt":
        pytest.skip("PTY-backed stdin is POSIX-only")

    fake_codex = tmp_path / "fake_codex.py"
    fake_codex.write_text(
        "import json, sys\n"
        "print(json.dumps({"
        "'type': 'item.completed', "
        "'item': {'type': 'agent_message', 'text': 'tty=' + str(sys.stdin.isatty()).lower()}"
        "}), flush=True)\n",
        encoding="utf-8",
    )
    runner = Runner(sys.executable, "danger-full-access", {}, "")
    outputs: list[str] = []

    async def run() -> int:
        proc = await runner.run(
            Options(
                repo_path=str(tmp_path),
                args=[str(fake_codex)],
                env={},
                on_output=lambda text: _append_output(outputs, text),
            )
        )
        return await proc.wait()

    assert asyncio.run(run()) == 0
    assert outputs == ["tty=true"]


async def _append_output(outputs: list[str], text: str) -> None:
    outputs.append(text)


def test_runner_parses_each_stdout_line_once(tmp_path, monkeypatch):
    import codebridge.codex as codexmod

    fake_codex = tmp_path / "codex_fake.py"
    fake_codex.write_text(
        "import json\n"
        "print(json.dumps({"
        "'type': 'item.completed', "
        "'thread_id': 't-1', "
        "'item': {'type': 'agent_message', 'text': 'hi'}"
        "}), flush=True)\n",
        encoding="utf-8",
    )

    calls = {"n": 0}
    real_parse = codexmod.parse_event

    def counting_parse(line):
        calls["n"] += 1
        return real_parse(line)

    monkeypatch.setattr(codexmod, "parse_event", counting_parse)

    received: list[tuple[str, object]] = []

    async def on_jsonl(line, evt):
        received.append((line, evt))

    runner = Runner(sys.executable, "danger-full-access", {}, "")

    async def run() -> int:
        proc = await runner.run(
            Options(
                repo_path=str(tmp_path),
                args=[str(fake_codex)],
                env={},
                on_jsonl=on_jsonl,
            )
        )
        rc = await proc.wait()
        assert proc.thread_id == "t-1"
        return rc

    assert asyncio.run(run()) == 0
    # A single JSON line must be parsed exactly once and the parsed event
    # forwarded to on_jsonl so downstream consumers do not re-parse it.
    assert calls["n"] == 1
    assert len(received) == 1
    line, evt = received[0]
    assert evt is not None and evt.type == "item.completed"


def test_runner_survives_oversized_stdout_line(tmp_path, monkeypatch):
    # A single JSONL line (e.g. a command_execution result embedding a large
    # tool output) that exceeds the stream buffer used to abort the whole run
    # with a misleading codex.exit error. Force a tiny limit here so a short
    # line reproduces the overrun without generating megabytes of test data.
    import codebridge.agents.base as base_mod

    monkeypatch.setattr(base_mod, "_STREAM_LIMIT", 200)

    fake_codex = tmp_path / "codex_fake.py"
    fake_codex.write_text(
        "import json\n"
        "print(json.dumps({"
        "'type': 'item.completed', "
        "'item': {'type': 'agent_message', 'text': 'x' * 500}"
        "}), flush=True)\n"
        "print(json.dumps({"
        "'type': 'item.completed', "
        "'thread_id': 't-2', "
        "'item': {'type': 'agent_message', 'text': 'hi'}"
        "}), flush=True)\n",
        encoding="utf-8",
    )

    received: list[tuple[str, object]] = []
    exits: list[tuple[object, int]] = []

    async def on_jsonl(line, evt):
        received.append((line, evt))

    async def on_exit(err, rc):
        exits.append((err, rc))

    runner = Runner(sys.executable, "danger-full-access", {}, "")

    async def run() -> int:
        proc = await runner.run(
            Options(
                repo_path=str(tmp_path),
                args=[str(fake_codex)],
                env={},
                on_jsonl=on_jsonl,
                on_exit=on_exit,
            )
        )
        rc = await proc.wait()
        # on_exit fires from a background task once stdout/stderr draining
        # finishes; give it a few loop iterations to run before asserting.
        for _ in range(200):
            if exits:
                break
            await asyncio.sleep(0.01)
        return rc

    assert asyncio.run(run()) == 0
    # The oversized first line is skipped rather than aborting the run; the
    # following line is still parsed normally and the run exits cleanly.
    assert len(received) == 1
    line, evt = received[0]
    assert evt is not None and evt.session_id == "t-2"
    assert exits and exits[0][0] is None


def test_toml_string_escapes_control_chars():
    rendered = _toml_string('a"b\nc\\d')
    assert rendered.startswith('"')
    assert rendered.endswith('"')
    assert "\\n" in rendered
    assert "\n" not in rendered


def test_codex_exec_accepts_all_option_order_variants_for_help(tmp_path):
    binary = shutil.which("codex")
    if not binary:
        pytest.skip("codex binary not available")

    groups = [
        ["--json"],
        ["--cd", str(tmp_path)],
        ["--sandbox", "workspace-write"],
        ["-c", 'approval_policy="on-request"'],
        ["-c", "sandbox_workspace_write.network_access=true"],
    ]
    failures: list[tuple[list[str], int, str]] = []

    for perm in itertools.permutations(groups):
        args = [binary, "exec"]
        for group in perm:
            args.extend(group)
        args.append("--help")
        proc = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
        if proc.returncode != 0:
            failures.append((args, proc.returncode, (proc.stderr or proc.stdout)[-400:]))

    assert not failures, failures[0] if failures else ""
