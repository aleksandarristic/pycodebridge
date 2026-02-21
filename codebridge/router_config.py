"""Helpers for rendering router configuration output."""

from __future__ import annotations

from .config import Config


def render_config_text(cfg: Config) -> str:
    """Render a concise config summary."""
    return (
        f"code_root: {cfg.codex.code_root}\n"
        f"sandbox: {cfg.codex.sandbox}\n"
        f"ask_for_approval: {cfg.codex.ask_for_approval}\n"
        f"network_access: {cfg.codex.network_access}\n"
        f"model: {cfg.codex.model}\n"
        f"model_reasoning_effort: {cfg.codex.model_reasoning_effort}\n"
        f"prefix: {cfg.discord.prefix}\n"
        f"allow_plain_prompts: {cfg.discord.allow_plain_prompts}\n"
        f"channel regex: {cfg.discord.channel_name_regex}\n"
        f"allowed_user_ids: {len(cfg.discord.allowed_user_ids)}\n"
        f"dm_admin_enabled: {cfg.discord.dm_admin_enabled}\n"
        f"dm_admin_user_ids: {len(cfg.discord.dm_admin_user_ids)}\n"
        f"totp_enabled: {cfg.discord.totp_enabled}\n"
        f"totp_window: {cfg.discord.totp_window}\n"
        f"totp_max_failures: {cfg.discord.totp_max_failures}\n"
        f"totp_failure_window_seconds: {cfg.discord.totp_failure_window_seconds}\n"
        f"totp_cooldown_seconds: {cfg.discord.totp_cooldown_seconds}"
    )
