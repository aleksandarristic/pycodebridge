"""Backward-compatible git bootstrap module shim."""

from __future__ import annotations

from .services import git_bootstrap as _impl

_settings = _impl._settings
_env_for_git = _impl._env_for_git
_repo_paths = _impl._repo_paths

apply_global = _impl.apply_global
apply_repo_local = _impl.apply_repo_local
apply_existing_repos_local = _impl.apply_existing_repos_local


async def bootstrap_startup(cfg, logger) -> None:
    """Run startup git bootstrap according to configuration.

    Kept as a wrapper so monkeypatching this module's helpers in tests
    continues to work after moving implementation into `services`.
    """
    if not cfg.git.enabled or not cfg.git.apply_on_startup:
        return
    global_ok = await apply_global(cfg, logger)
    if global_ok:
        return
    if cfg.git.local_fallback_on_global_failure and cfg.git.apply_to_existing_repos:
        await apply_existing_repos_local(cfg, logger)
