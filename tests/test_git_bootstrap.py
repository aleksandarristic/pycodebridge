import asyncio
import subprocess

from codebridge.config import Config
from codebridge import git_bootstrap


class _FakeLogger:
    def __init__(self) -> None:
        self.infos = []
        self.warnings = []

    def info(self, name: str, extra=None):
        self.infos.append((name, extra or {}))

    def warning(self, name: str, extra=None):
        self.warnings.append((name, extra or {}))


def test_apply_repo_local_sets_git_config(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=str(repo), check=True, capture_output=True, text=True)

    cfg = Config()
    cfg.codex.code_root = str(tmp_path)
    cfg.git.enabled = True
    cfg.git.user_name = "Dev User"
    cfg.git.user_email = "dev@example.com"
    cfg.git.credential_helper = "!gh auth git-credential"

    logger = _FakeLogger()
    ok = asyncio.run(git_bootstrap.apply_repo_local(cfg, logger, str(repo)))
    assert ok is True

    name = subprocess.run(
        ["git", "config", "--local", "--get", "user.name"],
        cwd=str(repo),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    email = subprocess.run(
        ["git", "config", "--local", "--get", "user.email"],
        cwd=str(repo),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    helper = subprocess.run(
        ["git", "config", "--local", "--get", "credential.helper"],
        cwd=str(repo),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert name == "Dev User"
    assert email == "dev@example.com"
    assert helper == "!gh auth git-credential"


def test_apply_global_writes_to_custom_global_config(tmp_path):
    code_root = tmp_path / "code_root"
    code_root.mkdir()
    cfg = Config()
    cfg.codex.code_root = str(code_root)
    cfg.git.enabled = True
    cfg.git.user_name = "Dev User"
    cfg.git.user_email = "dev@example.com"
    cfg.git.credential_helper = "!gh auth git-credential"
    cfg.git.global_config_path = str(tmp_path / "gitconfig")

    logger = _FakeLogger()
    ok = asyncio.run(git_bootstrap.apply_global(cfg, logger))
    assert ok is True

    name = subprocess.run(
        ["git", "config", "--file", str(tmp_path / "gitconfig"), "--get", "user.name"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert name == "Dev User"


def test_bootstrap_startup_falls_back_to_local_existing_repos(monkeypatch):
    cfg = Config()
    cfg.git.enabled = True
    cfg.git.apply_on_startup = True
    cfg.git.apply_to_existing_repos = True
    cfg.git.local_fallback_on_global_failure = True
    logger = _FakeLogger()
    calls = []

    async def _fake_apply_global(_cfg, _logger):
        return False

    async def _fake_apply_existing(_cfg, _logger):
        calls.append("existing")
        return 1

    monkeypatch.setattr(git_bootstrap, "apply_global", _fake_apply_global)
    monkeypatch.setattr(git_bootstrap, "apply_existing_repos_local", _fake_apply_existing)

    asyncio.run(git_bootstrap.bootstrap_startup(cfg, logger))
    assert calls == ["existing"]
