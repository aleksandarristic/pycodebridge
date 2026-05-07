from codebridge.commands.registry import (
    SURFACE_ADMIN,
    SURFACE_CORE,
    SURFACE_SUPPORT,
    build_registry,
    command_namespace,
    command_surface,
    render_help,
)


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
    assert "workflow" in registry
    assert "wf" in registry
    assert registry["wf"] is registry["workflow"]
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
    assert "Golden path:" in text
    assert "Promoted run shortcuts:" in text
    assert "Orientation:" in text
    assert "Session lifecycle:" in text
    assert "Active run control:" in text
    assert "Repo inspection:" in text
    assert "Advanced and support:" in text
    assert "Admin and maintenance:" in text
    assert "**`!c help [command]`**" in text
    assert "**`!c use <session>`**" in text
    assert "**`!c reset [session]`**" in text
    assert "**`!c workflow [session] <inspect|fix|review|ship> [focus]`**" in text
    assert "**`!a <text>`**" in text
    assert "**`!s <text>`**" in text
    assert "**`!y`**" in text
    assert "**`!n`**" in text
    assert "**`!c branch`**" in text
    assert "**`!c git <status|log|branches|branch|show|diff|remote|fetch|pull|add|commit|push|merge>`**" in text
    assert "**`!c gh <args>`**" in text
    assert "**`!c unlock [gh|all] [status|ttl]`**" in text
    assert "**`!c create`**" in text


def test_command_registry_detailed_help_uses_examples():
    registry, _ = build_registry()
    from codebridge.commands.help import render_help_command

    text = render_help_command(registry["git"], prefix="!c")
    assert "**Help: `git`**" in text
    assert "Preferred:" in text
    assert "Also available:" in text
    assert "Surface:" in text
    assert "Namespace:" in text
    assert "Examples:" in text
    assert "`!c git status`" in text


def test_command_registry_workflow_help_uses_examples():
    registry, _ = build_registry()
    from codebridge.commands.help import render_help_command

    text = render_help_command(registry["workflow"], prefix="!c")
    assert "**Help: `workflow`**" in text
    assert "`!c workflow list`" in text
    assert "`!c workflow inspect auth flow`" in text
    assert "`!c workflow review`" in text
    assert "`!c workflow fix failing tests`" in text


def test_command_registry_command_model_metadata():
    registry, _ = build_registry()
    assert command_surface(registry["status"]) == SURFACE_CORE
    assert command_namespace(registry["status"]) == "general"
    assert command_surface(registry["reset"]) == SURFACE_CORE
    assert command_namespace(registry["reset"]) == "session"
    assert command_surface(registry["choose"]) == SURFACE_SUPPORT
    assert command_surface(registry["audit"]) == SURFACE_ADMIN
    assert command_namespace(registry["audit"]) == "diag"
    assert command_surface(registry["create"]) == SURFACE_ADMIN
    assert command_namespace(registry["create"]) == "repo-admin"


def test_help_not_found_has_suggestions():
    registry, _ = build_registry()
    from codebridge.commands.help import help_not_found

    text = help_not_found("gti", registry, prefix="!c")
    assert "Unknown command `gti`." in text
    assert "`!c help git`" in text
