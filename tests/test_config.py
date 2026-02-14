
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
          guild_id: "123"
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


def test_load_config_totp_enabled_requires_secret_env(tmp_path, monkeypatch):
    code_root = tmp_path / "code"
    data_dir = tmp_path / "data"
    code_root.mkdir()
    data_dir.mkdir()

    monkeypatch.setenv("CODE_ROOT", str(code_root))
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.delenv("DISCORD_TOTP_SECRET", raising=False)

    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        """
        discord:
          guild_id: "123"
          allowed_user_ids: ["1"]
          totp_enabled: true
        codex:
          code_root: "$CODE_ROOT"
        state:
          data_dir: "%DATA_DIR%"
          log_dir: "%DATA_DIR%/logs"
        """,
        encoding="utf-8",
    )

    try:
        cfgmod.load(str(cfg_path))
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "discord TOTP secret env" in str(exc)


def test_load_config_totp_limiter_knobs(tmp_path, monkeypatch):
    code_root = tmp_path / "code"
    data_dir = tmp_path / "data"
    code_root.mkdir()
    data_dir.mkdir()

    monkeypatch.setenv("CODE_ROOT", str(code_root))
    monkeypatch.setenv("DATA_DIR", str(data_dir))

    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        """
        discord:
          guild_id: "123"
          allowed_user_ids: ["1"]
          totp_max_failures: 7
          totp_failure_window_seconds: 90
          totp_cooldown_seconds: 180
        codex:
          code_root: "$CODE_ROOT"
        state:
          data_dir: "%DATA_DIR%"
          log_dir: "%DATA_DIR%/logs"
        """,
        encoding="utf-8",
    )

    cfg = cfgmod.load(str(cfg_path))
    assert cfg.discord.totp_max_failures == 7
    assert cfg.discord.totp_failure_window_seconds == 90
    assert cfg.discord.totp_cooldown_seconds == 180


def test_load_config_totp_limiter_knobs_validation(tmp_path, monkeypatch):
    code_root = tmp_path / "code"
    data_dir = tmp_path / "data"
    code_root.mkdir()
    data_dir.mkdir()

    monkeypatch.setenv("CODE_ROOT", str(code_root))
    monkeypatch.setenv("DATA_DIR", str(data_dir))

    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        """
        discord:
          guild_id: "123"
          allowed_user_ids: ["1"]
          totp_max_failures: -1
        codex:
          code_root: "$CODE_ROOT"
        state:
          data_dir: "%DATA_DIR%"
          log_dir: "%DATA_DIR%/logs"
        """,
        encoding="utf-8",
    )

    try:
        cfgmod.load(str(cfg_path))
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "totp_max_failures" in str(exc)

    cfg_path.write_text(
        """
        discord:
          guild_id: "123"
          allowed_user_ids: ["1"]
          totp_failure_window_seconds: 0
        codex:
          code_root: "$CODE_ROOT"
        state:
          data_dir: "%DATA_DIR%"
          log_dir: "%DATA_DIR%/logs"
        """,
        encoding="utf-8",
    )
    try:
        cfgmod.load(str(cfg_path))
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "totp_failure_window_seconds" in str(exc)

    cfg_path.write_text(
        """
        discord:
          guild_id: "123"
          allowed_user_ids: ["1"]
          totp_cooldown_seconds: -1
        codex:
          code_root: "$CODE_ROOT"
        state:
          data_dir: "%DATA_DIR%"
          log_dir: "%DATA_DIR%/logs"
        """,
        encoding="utf-8",
    )
    try:
        cfgmod.load(str(cfg_path))
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "totp_cooldown_seconds" in str(exc)


def test_load_config_codex_approval_policy_validation(tmp_path, monkeypatch):
    code_root = tmp_path / "code"
    data_dir = tmp_path / "data"
    code_root.mkdir()
    data_dir.mkdir()

    monkeypatch.setenv("CODE_ROOT", str(code_root))
    monkeypatch.setenv("DATA_DIR", str(data_dir))

    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        """
        discord:
          guild_id: "123"
          allowed_user_ids: ["1"]
        codex:
          code_root: "$CODE_ROOT"
          ask_for_approval: "on-request"
        state:
          data_dir: "%DATA_DIR%"
          log_dir: "%DATA_DIR%/logs"
        """,
        encoding="utf-8",
    )
    cfg = cfgmod.load(str(cfg_path))
    assert cfg.codex.ask_for_approval == "on-request"

    cfg_path.write_text(
        """
        discord:
          guild_id: "123"
          allowed_user_ids: ["1"]
        codex:
          code_root: "$CODE_ROOT"
          ask_for_approval: "sometimes"
        state:
          data_dir: "%DATA_DIR%"
          log_dir: "%DATA_DIR%/logs"
        """,
        encoding="utf-8",
    )
    try:
        cfgmod.load(str(cfg_path))
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "codex.ask_for_approval" in str(exc)
