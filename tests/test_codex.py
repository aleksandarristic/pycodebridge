from codebridge.codex import Runner, display_texts, parse_event


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
    assert "-a" in args
    idx = args.index("-a")
    assert args[idx + 1] == "on-request"
    assert args[idx + 2] == "exec"
