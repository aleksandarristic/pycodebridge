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
    text = render_help(specs)
    assert "Commands:" in text
    assert "General:" in text
    assert "Auth tags: [open]=no TOTP" in text
    assert "help — show this help [open] (aliases: commands)" in text
    assert "unlock [gh|all] [status|ttl] — unlock command scopes for your account (status is open) [totp] (aliases: ul)" in text
    assert "lock [gh|all] — clear unlock scopes for your account [open] (aliases: lk)" in text
    assert "use <session> — set your sticky session [unlock/default] (aliases: select)" in text
    assert "reset [session] — reset session context [unlock/default]" in text
    assert "create — create repo in code_root and git init [totp] (aliases: createrepo, new)" in text
    assert "Repo helpers:" in text
    assert "git <status|log|branches|show|diff|remote|pull|commit|push|merge> — git helpers [mixed]" in text
    assert "gh <args> — GitHub CLI helper passthrough [unlock/gh]" in text
    assert "steer [session] -- <text> | steer <text> — send steering text to active Codex session [unlock/default]" in text
    assert "answer [session] -- <text> | answer <text> — send input to active Codex session [unlock/default] (aliases: reply)" in text
    assert "interrupt [session] — send ESC-like interrupt [unlock/default] (aliases: esc)" in text
    assert "wait — show sessions awaiting input [unlock/default]" in text
