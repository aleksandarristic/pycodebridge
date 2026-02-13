from codebridge.command_registry import build_registry, render_help


def test_command_registry_aliases():
    registry, specs = build_registry()
    assert "use" in registry
    assert "select" in registry
    assert registry["use"] is registry["select"]
    assert "/quit" in registry
    assert specs


def test_command_registry_help_text():
    _, specs = build_registry()
    text = render_help(specs)
    assert "Commands:" in text
    assert "General:" in text
    assert "help — show this help" in text
    assert "use/select <session> — set your sticky session" in text
    assert "Repo helpers:" in text
    assert "git <status|log|branches|show|diff|pull|commit|push|merge> — git helpers" in text
    assert "gh <args> — GitHub CLI helper passthrough" in text
