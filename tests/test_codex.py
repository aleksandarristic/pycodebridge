from codebridge.codex import display_texts, parse_event


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
