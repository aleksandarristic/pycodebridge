import itertools
import shutil
import subprocess

import pytest

from codebridge.codex import Runner, _toml_string, display_texts, parse_event


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


def test_runner_build_args_include_workspace_network_override_when_enabled():
    runner = Runner("codex", "workspace-write", {}, "on-request", network_access=True)
    args = runner.build_start_args("/tmp/repo", "hello", "", "")
    assert "sandbox_workspace_write.network_access=true" in args


def test_runner_build_args_skip_workspace_network_override_when_not_workspace_write():
    runner = Runner("codex", "read-only", {}, "on-request", network_access=True)
    args = runner.build_start_args("/tmp/repo", "hello", "", "")
    assert "sandbox_workspace_write.network_access=true" not in args


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
