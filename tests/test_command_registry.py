from codebridge.command_registry import build_registry, render_help


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
    assert "show" in registry
    assert "showrepo" in registry
    assert registry["showrepo"] is registry["show"]
    assert "changes" in registry
    assert "showchanges" in registry
    assert registry["showchanges"] is registry["changes"]
    assert "/quit" in registry
    assert specs


def test_command_registry_help_text():
    _, specs = build_registry()
    text = render_help(specs, prefix="!c")
    assert "Commands:" in text
    assert "General:" in text
    assert "Auth tags: [open]=no TOTP" in text
    assert "- **`!c help [command]`**, **`!c commands [command]`**, **`!help`** - show this help [open]" in text
    assert "**`!c unlock [gh|all] [status|ttl]`**" in text
    assert "**`!c ul [gh|all] [status|ttl]`**" in text
    assert "**`!unlock ...`**" in text
    assert "**`!ul ...`**" in text
    assert "- **`!c lock [gh|all]`**, **`!c lk [gh|all]`**" in text
    assert "**`!lock ...`**" in text
    assert "- **`!c use <session>`**, **`!c select <session>`** - set your sticky session [unlock/default]" in text
    assert "- **`!c reset [session]`** - reset session context [unlock/default]" in text
    assert "- **`!c create`**, **`!c createrepo`**, **`!c new`** - create repo in code_root and git init [totp]" in text
    assert "Repo helpers:" in text
    assert "**`!git ...`**" in text
    assert "**`!gh ...`**" in text
    assert "**`!steer <text>`**" in text
    assert "**`!a <text>`**" in text
    assert "**`!stop [session]`**" in text
    assert "**`!w`**" in text


def test_command_registry_detailed_help_uses_examples():
    registry, _ = build_registry()
    from codebridge.help_renderer import render_help_command

    text = render_help_command(registry["git"], prefix="!c")
    assert "**Help: `git`**" in text
    assert "Examples:" in text
    assert "`!c git status`" in text


def test_help_not_found_has_suggestions():
    registry, _ = build_registry()
    from codebridge.help_renderer import help_not_found

    text = help_not_found("gti", registry, prefix="!c")
    assert "Unknown command `gti`." in text
    assert "`!c help git`" in text
