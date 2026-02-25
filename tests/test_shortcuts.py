from codebridge.commands.shortcuts import normalize_bang_shortcut


def test_normalize_bang_shortcut_session_targeted_forms():
    assert normalize_bang_shortcut("!s:default keep changes", {"status"}) == "steer default -- keep changes"
    assert normalize_bang_shortcut("!a:blue yes", {"status"}) == "answer blue -- yes"


def test_normalize_bang_shortcut_short_forms():
    assert normalize_bang_shortcut("!s", {"status"}) == "steer"
    assert normalize_bang_shortcut("!a proceed", {"status"}) == "answer proceed"
    assert normalize_bang_shortcut("!continue", {"status"}) == "choose continue"


def test_normalize_bang_shortcut_generic_known_tokens():
    known = {"status", "u", "health"}
    assert normalize_bang_shortcut("!status", known) == "status"
    assert normalize_bang_shortcut("!u now", known) == "u now"
    assert normalize_bang_shortcut("!missing", known) == ""


def test_normalize_bang_shortcut_alias_mappings():
    known = {"help", "repos", "renamerepo"}
    aliases = (
        ("!commands", "help"),
        ("!rename", "renamerepo"),
    )
    assert normalize_bang_shortcut("!commands", known, aliases=aliases) == "help"
    assert normalize_bang_shortcut("!rename from to", known, aliases=aliases) == "renamerepo from to"
