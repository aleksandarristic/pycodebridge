from codebridge.config import Config
from codebridge.router_config import render_config_text


def test_render_config_text_includes_core_fields():
    cfg = Config()
    cfg.codex.code_root = "/tmp/code"
    cfg.codex.sandbox = "workspace-write"
    cfg.codex.ask_for_approval = "on-request"
    cfg.codex.model = "gpt-test"
    cfg.codex.model_reasoning_effort = "medium"
    cfg.discord.prefix = "!c"
    cfg.discord.allow_plain_prompts = True
    cfg.discord.channel_name_regex = "^codex-(.*)$"
    cfg.discord.allowed_user_ids = ["1", "2"]
    cfg.discord.dm_admin_enabled = True
    cfg.discord.dm_admin_user_ids = ["3"]
    cfg.discord.totp_enabled = True
    cfg.discord.totp_window = 2
    cfg.discord.totp_max_failures = 4
    cfg.discord.totp_failure_window_seconds = 120
    cfg.discord.totp_cooldown_seconds = 90

    text = render_config_text(cfg)
    assert "code_root: /tmp/code" in text
    assert "sandbox: workspace-write" in text
    assert "ask_for_approval: on-request" in text
    assert "model: gpt-test" in text
    assert "model_reasoning_effort: medium" in text
    assert "prefix: !c" in text
    assert "allow_plain_prompts: True" in text
    assert "channel regex: ^codex-(.*)$" in text
    assert "allowed_user_ids: 2" in text
    assert "dm_admin_enabled: True" in text
    assert "dm_admin_user_ids: 1" in text
    assert "totp_enabled: True" in text
    assert "totp_window: 2" in text
    assert "totp_max_failures: 4" in text
    assert "totp_failure_window_seconds: 120" in text
    assert "totp_cooldown_seconds: 90" in text
