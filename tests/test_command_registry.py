from codebridge.commands.registry import build_registry, render_help


def test_command_registry_aliases():
    registry, specs = build_registry()
    assert "use" in registry
    assert "select" in registry
    assert registry["use"] is registry["select"]
    assert "new" in registry
    assert registry["new"] is registry["create"]
    assert "copy" in registry
    assert "cp" in registry
    assert registry["cp"] is registry["copy"]
    assert "cfg" in registry
    assert registry["cfg"] is registry["config"]
    assert "health" in registry
    assert "diag" in registry
    assert registry["diag"] is registry["health"]
    assert "updates" in registry
    assert "u" in registry
    assert registry["u"] is registry["updates"]
    assert "session" in registry
    assert "sess" in registry
    assert registry["sess"] is registry["session"]
    assert "budget" in registry
    assert "budgets" in registry
    assert registry["budgets"] is registry["budget"]
    assert "audit" in registry
    assert "show" in registry
    assert "showrepo" in registry
    assert registry["showrepo"] is registry["show"]
    assert "changes" in registry
    assert "showchanges" in registry
    assert registry["showchanges"] is registry["changes"]
    assert "stop" in registry
    assert "pause" in registry
    assert registry["pause"] is registry["stop"]
    assert "interrupt" in registry
    assert "int" in registry
    assert "esc" in registry
    assert "escape" in registry
    assert registry["int"] is registry["interrupt"]
    assert registry["esc"] is registry["interrupt"]
    assert registry["escape"] is registry["interrupt"]
    assert "approve" in registry
    assert "y" in registry
    assert registry["y"] is registry["approve"]
    assert "deny" in registry
    assert "n" in registry
    assert registry["n"] is registry["deny"]
    assert "wait" in registry
    assert "w" in registry
    assert registry["w"] is registry["wait"]
    assert "/quit" in registry
    assert specs


def test_command_registry_help_text():
    _, specs = build_registry()
    text = render_help(specs, prefix="!c")
    assert "Commands:" in text
    assert "General:" in text
    assert "Auth tags: [open]=no TOTP" in text
    assert "**`!c help [command]`**" in text
    assert "**`!c commands [command]`**" in text
    assert "**`!help [command]`**" in text
    assert "**`!commands [command]`**" in text
    assert "**`!cfg`**" in text
    assert "**`!opts [show]`**" in text
    assert "**`!health`**" in text
    assert "**`!diag`**" in text
    assert "**`!c unlock [gh|all] [status|ttl]`**" in text
    assert "**`!c ul [gh|all] [status|ttl]`**" in text
    assert "**`!unlock [gh|all] [status|ttl]`**" in text
    assert "**`!ul [gh|all] [status|ttl]`**" in text
    assert "**`!c lock [gh|all]`**" in text
    assert "**`!c lk [gh|all]`**" in text
    assert "**`!lock [gh|all]`**" in text
    assert "**`!c use <session>`**" in text
    assert "**`!c select <session>`**" in text
    assert "**`!c reset [session]`**" in text
    assert "**`!c create`**" in text
    assert "**`!c createrepo`**" in text
    assert "**`!c new`**" in text
    assert "Repo helpers:" in text
    assert "**`!git <status|log|branches|branch|show|diff|remote|fetch|pull|add|commit|push|merge>`**" in text
    assert "**`!gh <args>`**" in text
    assert "**`!steer <text>`**" in text
    assert "**`!a <text>`**" in text
    assert "**`!stop [session]`**" in text
    assert "**`!interrupt [session]`**" in text
    assert "**`!int [session]`**" in text
    assert "**`!esc [session]`**" in text
    assert "**`!escape [session]`**" in text
    assert "**`!w`**" in text


def test_command_registry_detailed_help_uses_examples():
    registry, _ = build_registry()
    from codebridge.commands.help import render_help_command

    text = render_help_command(registry["git"], prefix="!c")
    assert "**Help: `git`**" in text
    assert "Examples:" in text
    assert "`!c git status`" in text


def test_help_not_found_has_suggestions():
    registry, _ = build_registry()
    from codebridge.commands.help import help_not_found

    text = help_not_found("gti", registry, prefix="!c")
    assert "Unknown command `gti`." in text
    assert "`!c help git`" in text
