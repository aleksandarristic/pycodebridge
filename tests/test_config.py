import os
from pathlib import Path

from codebridge import config as cfgmod


def test_load_config_expands_paths(tmp_path, monkeypatch):
    code_root = tmp_path / "code"
    data_dir = tmp_path / "data"
    log_dir = data_dir / "logs"
    code_root.mkdir()
    data_dir.mkdir()

    monkeypatch.setenv("CODE_ROOT", str(code_root))
    monkeypatch.setenv("DATA_DIR", str(data_dir))

    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        """
        discord:
          allowed_user_ids: ["1"]
        codex:
          code_root: "$CODE_ROOT"
        state:
          data_dir: "%DATA_DIR%"
          log_dir: "%DATA_DIR%/logs"
        """,
        encoding="utf-8",
    )

    cfg = cfgmod.load(str(cfg_path))
    assert cfg.codex.code_root == str(code_root)
    assert cfg.state.data_dir == str(data_dir)
    assert cfg.state.log_dir == str(log_dir)
    assert cfg.discord.prefix == cfgmod.DEFAULT_PREFIX
