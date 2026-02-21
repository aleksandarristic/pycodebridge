"""Git bootstrap helpers for startup and repo lifecycle flows."""

from __future__ import annotations

import os
from typing import Any

from .config import Config
from .router_helpers import HELPER_TIMEOUT, run_limited_command


def _settings(cfg: Config) -> list[tuple[str, str]]:
    if not cfg.git.enabled:
        return []
    settings: list[tuple[str, str]] = []
    if (cfg.git.user_name or "").strip():
        settings.append(("user.name", cfg.git.user_name.strip()))
    if (cfg.git.user_email or "").strip():
        settings.append(("user.email", cfg.git.user_email.strip()))
    if (cfg.git.credential_helper or "").strip():
        settings.append(("credential.helper", cfg.git.credential_helper.strip()))
    return settings


def _env_for_git(cfg: Config) -> dict[str, str] | None:
    path = (cfg.git.global_config_path or "").strip()
    if not path:
        return None
    env = os.environ.copy()
    env["GIT_CONFIG_GLOBAL"] = path
    return env


async def apply_global(cfg: Config, logger: Any) -> bool:
    """Apply git bootstrap settings globally; return True on success."""
    settings = _settings(cfg)
    if not settings:
        return True
    base = cfg.codex.code_root or "."
    env = _env_for_git(cfg)
    for key, value in settings:
        out, err = await run_limited_command(
            base,
            ["git", "config", "--global", key, value],
            timeout=HELPER_TIMEOUT,
            env=env,
        )
        if err:
            logger.warning(
                "git.bootstrap.global_failed",
                extra={"key": key, "error": str(err), "output": out[-400:]},
            )
            return False
    logger.info("git.bootstrap.global_ok", extra={"settings": [k for k, _ in settings]})
    return True


async def apply_repo_local(cfg: Config, logger: Any, repo_path: str) -> bool:
    """Apply git bootstrap settings to a specific repo's local config."""
    settings = _settings(cfg)
    if not settings:
        return True
    for key, value in settings:
        out, err = await run_limited_command(
            repo_path,
            ["git", "config", "--local", key, value],
            timeout=HELPER_TIMEOUT,
        )
        if err:
            logger.warning(
                "git.bootstrap.local_failed",
                extra={"repo_path": repo_path, "key": key, "error": str(err), "output": out[-400:]},
            )
            return False
    logger.info("git.bootstrap.local_ok", extra={"repo_path": repo_path, "settings": [k for k, _ in settings]})
    return True


def _repo_paths(code_root: str) -> list[str]:
    if not code_root or not os.path.isdir(code_root):
        return []
    repos: list[str] = []
    for name in sorted(os.listdir(code_root)):
        path = os.path.join(code_root, name)
        if os.path.isdir(path) and os.path.isdir(os.path.join(path, ".git")):
            repos.append(path)
    return repos


async def apply_existing_repos_local(cfg: Config, logger: Any) -> int:
    """Apply local git bootstrap settings to all repos under code_root."""
    applied = 0
    for repo_path in _repo_paths(cfg.codex.code_root):
        ok = await apply_repo_local(cfg, logger, repo_path)
        if ok:
            applied += 1
    logger.info("git.bootstrap.local_existing_done", extra={"applied": applied})
    return applied


async def bootstrap_startup(cfg: Config, logger: Any) -> None:
    """Run startup git bootstrap according to configuration."""
    if not cfg.git.enabled or not cfg.git.apply_on_startup:
        return
    global_ok = await apply_global(cfg, logger)
    if global_ok:
        return
    if cfg.git.local_fallback_on_global_failure and cfg.git.apply_to_existing_repos:
        await apply_existing_repos_local(cfg, logger)
