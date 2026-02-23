
import dataclasses

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


def test_load_config_codex_network_access_toggle(tmp_path, monkeypatch):
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
          network_access: true
        state:
          data_dir: "%DATA_DIR%"
          log_dir: "%DATA_DIR%/logs"
        """,
        encoding="utf-8",
    )
    cfg = cfgmod.load(str(cfg_path))
    assert cfg.codex.network_access is True


def test_load_config_runtime_health_fields(tmp_path, monkeypatch):
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
        state:
          data_dir: "%DATA_DIR%"
          log_dir: "%DATA_DIR%/logs"
        runtime:
          log_level: "info"
          health_bind: "127.0.0.1:8080"
          health_path: "health"
          run_heartbeat_seconds: 90
          run_completion_min_seconds: 420
          show_reasoning_details: false
        """,
        encoding="utf-8",
    )
    cfg = cfgmod.load(str(cfg_path))
    assert cfg.runtime.health_bind == "127.0.0.1:8080"
    assert cfg.runtime.health_path == "/health"
    assert cfg.runtime.run_heartbeat_seconds == 90
    assert cfg.runtime.run_completion_min_seconds == 420
    assert cfg.runtime.show_reasoning_details is False


def test_load_config_boolean_string_values(tmp_path, monkeypatch):
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
          allow_plain_prompts: "false"
          dm_admin_enabled: "false"
          totp_enabled: "false"
        telegram:
          allow_plain_prompts: "false"
        codex:
          code_root: "$CODE_ROOT"
          network_access: "false"
        state:
          data_dir: "%DATA_DIR%"
          log_dir: "%DATA_DIR%/logs"
        runtime:
          show_reasoning_details: "false"
        audit:
          redact: "false"
        git:
          enabled: "false"
          apply_on_startup: "false"
          apply_to_existing_repos: "false"
          apply_on_repo_create_clone_copy: "false"
          local_fallback_on_global_failure: "false"
          allow_dangerous_ops: "false"
          require_confirmation_for_dangerous_ops: "false"
        """,
        encoding="utf-8",
    )
    cfg = cfgmod.load(str(cfg_path))
    assert cfg.discord.allow_plain_prompts is False
    assert cfg.discord.dm_admin_enabled is False
    assert cfg.discord.totp_enabled is False
    assert cfg.telegram.allow_plain_prompts is False
    assert cfg.codex.network_access is False
    assert cfg.runtime.show_reasoning_details is False
    assert cfg.audit.redact is False
    assert cfg.git.enabled is False
    assert cfg.git.apply_on_startup is False
    assert cfg.git.apply_to_existing_repos is False
    assert cfg.git.apply_on_repo_create_clone_copy is False
    assert cfg.git.local_fallback_on_global_failure is False
    assert cfg.git.allow_dangerous_ops is False
    assert cfg.git.require_confirmation_for_dangerous_ops is False


def test_load_config_invalid_boolean_string_fails(tmp_path, monkeypatch):
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
        state:
          data_dir: "%DATA_DIR%"
          log_dir: "%DATA_DIR%/logs"
        runtime:
          show_reasoning_details: "maybe"
        """,
        encoding="utf-8",
    )
    try:
        cfgmod.load(str(cfg_path))
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "runtime.show_reasoning_details" in str(exc)


def test_repo_bootstrap_config_is_dataclass():
    assert dataclasses.is_dataclass(cfgmod.RepoBootstrapConfig)


def test_load_config_git_bootstrap_fields(tmp_path, monkeypatch):
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
        state:
          data_dir: "%DATA_DIR%"
          log_dir: "%DATA_DIR%/logs"
        git:
          enabled: true
          user_name: "Dev User"
          user_email: "dev@example.com"
          credential_helper: "!gh auth git-credential"
          global_config_path: "%DATA_DIR%/gitconfig"
          apply_on_startup: true
          apply_to_existing_repos: true
          apply_on_repo_create_clone_copy: true
          local_fallback_on_global_failure: true
          allow_dangerous_ops: true
          require_confirmation_for_dangerous_ops: true
          dangerous_confirmation_token: "--really-do-it"
        """,
        encoding="utf-8",
    )

    cfg = cfgmod.load(str(cfg_path))
    assert cfg.git.enabled is True
    assert cfg.git.user_name == "Dev User"
    assert cfg.git.user_email == "dev@example.com"
    assert cfg.git.credential_helper == "!gh auth git-credential"
    assert cfg.git.global_config_path == str(data_dir / "gitconfig")
    assert cfg.git.apply_on_startup is True
    assert cfg.git.apply_to_existing_repos is True
    assert cfg.git.apply_on_repo_create_clone_copy is True
    assert cfg.git.local_fallback_on_global_failure is True
    assert cfg.git.allow_dangerous_ops is True
    assert cfg.git.require_confirmation_for_dangerous_ops is True
    assert cfg.git.dangerous_confirmation_token == "--really-do-it"
