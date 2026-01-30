from codebridge.config import Config
from codebridge.router_config import render_config_text


def test_render_config_text_includes_core_fields():
    cfg = Config()
    cfg.codex.code_root = "/tmp/code"
    cfg.codex.sandbox = "workspace-write"
    cfg.codex.model = "gpt-test"
    cfg.codex.model_reasoning_effort = "medium"
    cfg.discord.prefix = "!c"
    cfg.discord.allow_plain_prompts = True
    cfg.discord.channel_name_regex = "^codex-(.*)$"
    cfg.discord.allowed_user_ids = ["1", "2"]
    cfg.discord.dm_admin_enabled = True
    cfg.discord.dm_admin_user_ids = ["3"]

    text = render_config_text(cfg)
    assert "code_root: /tmp/code" in text
    assert "sandbox: workspace-write" in text
    assert "model: gpt-test" in text
    assert "model_reasoning_effort: medium" in text
    assert "prefix: !c" in text
    assert "allow_plain_prompts: True" in text
    assert "channel regex: ^codex-(.*)$" in text
    assert "allowed_user_ids: 2" in text
    assert "dm_admin_enabled: True" in text
    assert "dm_admin_user_ids: 1" in text
