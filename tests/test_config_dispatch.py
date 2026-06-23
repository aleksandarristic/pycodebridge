"""Tests for DispatchConfig loading and validation."""

import textwrap
import pytest
from codebridge import config as cfgmod


def _write_cfg(tmp_path, extra: str = "") -> str:
    base = textwrap.dedent("""\
        discord:
          token_env: DISCORD_TOKEN
          guild_id: "123"
          allowed_user_ids: ["1"]
        codex:
          code_root: /tmp/code
        state:
          data_dir: /tmp/state
    """)
    content = base + textwrap.dedent(extra)
    path = tmp_path / "config.yaml"
    path.write_text(content)
    return str(path)


def test_dispatch_defaults_when_section_absent(tmp_path):
    path = _write_cfg(tmp_path)
    cfg = cfgmod.load(path)
    assert cfg.dispatch.output_mode == "both"
    assert cfg.dispatch.close_mode == "pr"
    assert "{{USER_REQUEST}}" in cfg.dispatch.plan_prompt


def test_dispatch_output_mode_loaded(tmp_path):
    path = _write_cfg(tmp_path, """\
        dispatch:
          output_mode: per_agent
    """)
    cfg = cfgmod.load(path)
    assert cfg.dispatch.output_mode == "per_agent"


def test_dispatch_close_mode_loaded(tmp_path):
    path = _write_cfg(tmp_path, """\
        dispatch:
          close_mode: merge
    """)
    cfg = cfgmod.load(path)
    assert cfg.dispatch.close_mode == "merge"


def test_dispatch_plan_prompt_override(tmp_path):
    path = _write_cfg(tmp_path, """\
        dispatch:
          plan_prompt: "Custom prompt {{USER_REQUEST}}"
    """)
    cfg = cfgmod.load(path)
    assert cfg.dispatch.plan_prompt == "Custom prompt {{USER_REQUEST}}"


def test_dispatch_output_mode_validation_rejects_unknown(tmp_path):
    path = _write_cfg(tmp_path, """\
        dispatch:
          output_mode: weird
    """)
    with pytest.raises(ValueError, match="dispatch.output_mode"):
        cfgmod.load(path)


def test_dispatch_close_mode_validation_rejects_unknown(tmp_path):
    path = _write_cfg(tmp_path, """\
        dispatch:
          close_mode: auto
    """)
    with pytest.raises(ValueError, match="dispatch.close_mode"):
        cfgmod.load(path)


def test_dispatch_aggregate_mode_valid(tmp_path):
    path = _write_cfg(tmp_path, """\
        dispatch:
          output_mode: aggregate
    """)
    cfg = cfgmod.load(path)
    assert cfg.dispatch.output_mode == "aggregate"


def test_dispatch_both_modes_round_trip(tmp_path):
    path = _write_cfg(tmp_path, """\
        dispatch:
          output_mode: both
          close_mode: pr
    """)
    cfg = cfgmod.load(path)
    assert cfg.dispatch.output_mode == "both"
    assert cfg.dispatch.close_mode == "pr"
