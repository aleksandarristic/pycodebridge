from codebridge.commands.parse import parse_session_quit_alias, parse_session_slash_prompt


def test_parse_session_quit_alias():
    assert parse_session_quit_alias(["foo", "/quit"]) == "foo"
    assert parse_session_quit_alias(["foo", "bar"]) == ""
    assert parse_session_quit_alias(["/quit"]) == ""


def test_parse_session_slash_prompt():
    assert parse_session_slash_prompt("/model") == ("default", "/model")
    assert parse_session_slash_prompt("foo /quit") == ("foo", "/quit")
    assert parse_session_slash_prompt("foo /model bar") == ("foo", "/model bar")
    assert parse_session_slash_prompt("resume default hi") == ("", "")
