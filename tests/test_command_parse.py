from codebridge.commands.parse import parse_choose, parse_session_quit_alias, parse_session_slash_prompt


def test_parse_session_quit_alias():
    assert parse_session_quit_alias(["foo", "/quit"]) == "foo"
    assert parse_session_quit_alias(["foo", "bar"]) == ""
    assert parse_session_quit_alias(["/quit"]) == ""


def test_parse_session_slash_prompt():
    assert parse_session_slash_prompt("/model") == ("default", "/model")
    assert parse_session_slash_prompt("foo /quit") == ("foo", "/quit")
    assert parse_session_slash_prompt("foo /model bar") == ("foo", "/model bar")
    assert parse_session_slash_prompt("resume default hi") == ("", "")


def test_parse_choose_supports_continue_and_new_aliases():
    assert parse_choose("continue") == ("continue", "")
    assert parse_choose("cont") == ("cont", "")
    assert parse_choose("new") == ("new", "")
    assert parse_choose("alpha continue") == ("continue", "alpha")
    assert parse_choose("alpha cont") == ("cont", "alpha")
    assert parse_choose("alpha new") == ("new", "alpha")
