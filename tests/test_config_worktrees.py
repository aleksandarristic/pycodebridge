import textwrap

import pytest

from codebridge import config as cfgmod


def _write_cfg(tmp_path, monkeypatch, extra: str = "") -> str:
    code_root = tmp_path / "code"
    data_dir = tmp_path / "data"
    code_root.mkdir()
    data_dir.mkdir()
    monkeypatch.setenv("CODE_ROOT", str(code_root))
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    path = tmp_path / "config.yaml"
    base = textwrap.dedent(f"""\
        discord:
          guild_id: "123"
          allowed_user_ids: ["1"]
        codex:
          code_root: "$CODE_ROOT"
        state:
          data_dir: "$DATA_DIR"
          log_dir: "$DATA_DIR/logs"
        """)
    path.write_text(base + textwrap.dedent(extra), encoding="utf-8")
    return str(path)


def test_worktrees_defaults_when_absent(tmp_path, monkeypatch):
    cfg = cfgmod.load(_write_cfg(tmp_path, monkeypatch))
    assert cfg.worktrees.enabled is False
    assert cfg.worktrees.session_isolation is False
    assert cfg.worktrees.base_dir == ""
    assert cfg.worktrees.max_per_repo == cfgmod.DEFAULT_WORKTREE_MAX_PER_REPO
    assert cfg.worktrees.cleanup_on_end == "remove"


def test_worktrees_enabled_true(tmp_path, monkeypatch):
    cfg = cfgmod.load(_write_cfg(tmp_path, monkeypatch, "worktrees:\n  enabled: true"))
    assert cfg.worktrees.enabled is True


def test_worktrees_all_fields(tmp_path, monkeypatch):
    extra = """\
        worktrees:
          enabled: true
          session_isolation: true
          base_dir: "/tmp/wt"
          max_per_repo: 4
          cleanup_on_end: keep
        """
    cfg = cfgmod.load(_write_cfg(tmp_path, monkeypatch, extra))
    assert cfg.worktrees.enabled is True
    assert cfg.worktrees.session_isolation is True
    assert cfg.worktrees.base_dir == "/tmp/wt"
    assert cfg.worktrees.max_per_repo == 4
    assert cfg.worktrees.cleanup_on_end == "keep"


def test_worktrees_session_isolation_explicit_false(tmp_path, monkeypatch):
    cfg = cfgmod.load(_write_cfg(tmp_path, monkeypatch, "worktrees:\n  session_isolation: false"))
    assert cfg.worktrees.session_isolation is False


def test_worktrees_base_dir_expands_env(tmp_path, monkeypatch):
    wt_dir = tmp_path / "worktrees"
    wt_dir.mkdir()
    monkeypatch.setenv("WT_DIR", str(wt_dir))
    extra = "worktrees:\n  base_dir: \"$WT_DIR\""
    cfg = cfgmod.load(_write_cfg(tmp_path, monkeypatch, extra))
    assert cfg.worktrees.base_dir == str(wt_dir)


def test_worktrees_cleanup_on_end_pr(tmp_path, monkeypatch):
    cfg = cfgmod.load(_write_cfg(tmp_path, monkeypatch, "worktrees:\n  cleanup_on_end: pr"))
    assert cfg.worktrees.cleanup_on_end == "pr"


def test_worktrees_invalid_cleanup_raises(tmp_path, monkeypatch):
    extra = "worktrees:\n  cleanup_on_end: destroy"
    with pytest.raises(ValueError, match="worktrees.cleanup_on_end must be"):
        cfgmod.load(_write_cfg(tmp_path, monkeypatch, extra))


def test_worktrees_max_per_repo_zero_raises(tmp_path, monkeypatch):
    extra = "worktrees:\n  max_per_repo: 0"
    with pytest.raises(ValueError, match="worktrees.max_per_repo must be between"):
        cfgmod.load(_write_cfg(tmp_path, monkeypatch, extra))


def test_worktrees_max_per_repo_too_large_raises(tmp_path, monkeypatch):
    extra = "worktrees:\n  max_per_repo: 100"
    with pytest.raises(ValueError, match="worktrees.max_per_repo must be between"):
        cfgmod.load(_write_cfg(tmp_path, monkeypatch, extra))


def test_worktrees_max_per_repo_boundary_64(tmp_path, monkeypatch):
    extra = "worktrees:\n  max_per_repo: 64"
    cfg = cfgmod.load(_write_cfg(tmp_path, monkeypatch, extra))
    assert cfg.worktrees.max_per_repo == 64
