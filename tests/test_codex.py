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
    assert "--sandbox" in args
    assert "workspace-write" in args
    assert 'approval_policy="on-request"' in args
    assert "exec" in args


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
