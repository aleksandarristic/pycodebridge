"""Configuration loading and validation for the bridge."""

import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import yaml

DEFAULT_PREFIX = "!c"
DEFAULT_CHANNEL_REGEX = r"^codex-([A-Za-z0-9._-]+)$"
DEFAULT_MAX_DISCORD_CHARS = 1800
DEFAULT_SANDBOX = "workspace-write"
DEFAULT_LOG_LEVEL = "info"
DEFAULT_TOKEN_ENV = "DISCORD_TOKEN"
DEFAULT_TELEGRAM_TOKEN_ENV = "TELEGRAM_TOKEN"
DEFAULT_LOCK_TIMEOUT_SECONDS = 600
DEFAULT_CONFLICT_TTL_SECONDS = 60
DEFAULT_TRANSPORT_ADAPTER = "discord"
DEFAULT_AUDIT_REDACT = False
DEFAULT_MAX_UPLOAD_MB = 200

DEFAULT_START_PROMPT = (
    "Hello. This is a Discord-bridged Codex session for repo: {{REPO_NAME}}.\n"
    "Operate inside this repo directory. Stream outputs plainly. Be concise in your responses.\n"
)

DEFAULT_SPEC_PROMPT = (
    "Please ask me for a project spec for repo {{REPO_NAME}}.\n"
    "When the spec is finalized, write it to instructions/spec.md.\n"
    "Then create instructions/tasks/pending.md with a numbered task list and "
    "append a milestone entry to instructions/progress_log.md, "
    "following the pattern used in this repo.\n"
    "After writing the files, summarize what you produced."
    "Be concise in your responses.\n"
)


@dataclass
class DiscordConfig:
    """Discord-related configuration."""
    token_env: str = DEFAULT_TOKEN_ENV
    guild_id: str = ""
    allowed_user_ids: List[str] = field(default_factory=list)
    prefix: str = DEFAULT_PREFIX
    channel_name_regex: str = DEFAULT_CHANNEL_REGEX
    max_discord_message_chars: int = DEFAULT_MAX_DISCORD_CHARS
    allow_plain_prompts: bool = False
    dm_admin_enabled: bool = False
    dm_admin_user_ids: List[str] = field(default_factory=list)
    totp_enabled: bool = False
    totp_secret_env: str = "DISCORD_TOTP_SECRET"
    totp_window: int = 1

    _compiled_regex: Optional[re.Pattern] = field(default=None, init=False, repr=False)


@dataclass
class TelegramConfig:
    """Telegram-related configuration."""
    token_env: str = DEFAULT_TELEGRAM_TOKEN_ENV
    allowed_user_ids: List[str] = field(default_factory=list)
    prefix: str = DEFAULT_PREFIX
    channel_name_regex: str = DEFAULT_CHANNEL_REGEX
    allow_plain_prompts: bool = False

    _compiled_regex: Optional[re.Pattern] = field(default=None, init=False, repr=False)


@dataclass
class CodexConfig:
    """Codex CLI configuration."""
    binary: str = "codex"
    code_root: str = ""
    sandbox: str = DEFAULT_SANDBOX
    json: bool = True
    start_prompt: str = DEFAULT_START_PROMPT
    model: str = ""
    model_reasoning_effort: str = ""
    env: Dict[str, str] = field(default_factory=dict)


@dataclass
class StateConfig:
    """State persistence configuration."""
    data_dir: str = ""
    lock_timeout_seconds: int = DEFAULT_LOCK_TIMEOUT_SECONDS
    conflict_ttl_seconds: int = DEFAULT_CONFLICT_TTL_SECONDS
    log_dir: str = ""


@dataclass
class RuntimeConfig:
    """Runtime logging configuration."""
    log_level: str = DEFAULT_LOG_LEVEL


@dataclass
class AuditConfig:
    """Audit logging configuration."""
    redact: bool = DEFAULT_AUDIT_REDACT
    redact_patterns: List[str] = field(default_factory=list)


@dataclass
class TransportConfig:
    """Transport adapter configuration."""
    adapter: str = DEFAULT_TRANSPORT_ADAPTER


@dataclass
@dataclass
class FilesConfig:
    """File transfer configuration."""
    max_upload_mb: int = DEFAULT_MAX_UPLOAD_MB


class RepoBootstrapConfig:
    """Repo bootstrap configuration for createrepo/spec flows."""
    agents_template: str = ""
    spec_prompt: str = DEFAULT_SPEC_PROMPT


@dataclass
class Config:
    """Top-level configuration container."""
    discord: DiscordConfig = field(default_factory=DiscordConfig)
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    codex: CodexConfig = field(default_factory=CodexConfig)
    state: StateConfig = field(default_factory=StateConfig)
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)
    audit: AuditConfig = field(default_factory=AuditConfig)
    transport: TransportConfig = field(default_factory=TransportConfig)
    files: FilesConfig = field(default_factory=FilesConfig)
    repo_bootstrap: RepoBootstrapConfig = field(default_factory=RepoBootstrapConfig)

    def discord_token(self) -> str:
        """Return the Discord token from the configured env var."""
        env_name = self.discord.token_env or DEFAULT_TOKEN_ENV
        token = os.getenv(env_name, "").strip()
        if not token:
            raise ValueError(f"discord token env {env_name!r} is empty")
        return token

    def channel_regex(self) -> re.Pattern:
        """Compile and return the Discord channel name regex."""
        if self.discord._compiled_regex is None:
            self.discord._compiled_regex = re.compile(self.discord.channel_name_regex)
        return self.discord._compiled_regex

    def channel_regex_for(self, platform: str) -> re.Pattern:
        """Compile and return the channel name regex for a platform."""
        if platform == "telegram":
            if self.telegram._compiled_regex is None:
                self.telegram._compiled_regex = re.compile(self.telegram.channel_name_regex)
            return self.telegram._compiled_regex
        return self.channel_regex()

    def telegram_token(self) -> str:
        """Return the Telegram token from the configured env var."""
        env_name = self.telegram.token_env or DEFAULT_TELEGRAM_TOKEN_ENV
        token = os.getenv(env_name, "").strip()
        if not token:
            raise ValueError(f"telegram token env {env_name!r} is empty")
        return token


def load(path: str) -> Config:
    """Load configuration from YAML and apply defaults/validation."""
    if not path:
        raise ValueError("config path is required")
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    cfg = Config()
    _apply_dict(cfg, raw)
    _apply_defaults(cfg)
    _expand_paths(cfg)
    _validate(cfg)
    return cfg


def _apply_dict(cfg: Config, raw: dict) -> None:
    """Apply raw dictionary values onto the Config object."""
    discord = raw.get("discord", {}) or {}
    cfg.discord.token_env = discord.get("token_env", cfg.discord.token_env)
    cfg.discord.guild_id = discord.get("guild_id", cfg.discord.guild_id)
    cfg.discord.allowed_user_ids = list(discord.get("allowed_user_ids", cfg.discord.allowed_user_ids) or [])
    cfg.discord.prefix = discord.get("prefix", cfg.discord.prefix)
    cfg.discord.channel_name_regex = discord.get("channel_name_regex", cfg.discord.channel_name_regex)
    cfg.discord.max_discord_message_chars = int(
        discord.get("max_discord_message_chars", cfg.discord.max_discord_message_chars)
    )
    cfg.discord.allow_plain_prompts = bool(discord.get("allow_plain_prompts", cfg.discord.allow_plain_prompts))
    cfg.discord.dm_admin_enabled = bool(discord.get("dm_admin_enabled", cfg.discord.dm_admin_enabled))
    cfg.discord.dm_admin_user_ids = list(discord.get("dm_admin_user_ids", cfg.discord.dm_admin_user_ids) or [])
    cfg.discord.totp_enabled = bool(discord.get("totp_enabled", cfg.discord.totp_enabled))
    cfg.discord.totp_secret_env = discord.get("totp_secret_env", cfg.discord.totp_secret_env)
    cfg.discord.totp_window = int(discord.get("totp_window", cfg.discord.totp_window))

    telegram = raw.get("telegram", {}) or {}
    cfg.telegram.token_env = telegram.get("token_env", cfg.telegram.token_env)
    cfg.telegram.allowed_user_ids = list(telegram.get("allowed_user_ids", cfg.telegram.allowed_user_ids) or [])
    cfg.telegram.prefix = telegram.get("prefix", cfg.telegram.prefix)
    cfg.telegram.channel_name_regex = telegram.get("channel_name_regex", cfg.telegram.channel_name_regex)
    cfg.telegram.allow_plain_prompts = bool(telegram.get("allow_plain_prompts", cfg.telegram.allow_plain_prompts))

    codex = raw.get("codex", {}) or {}
    cfg.codex.binary = codex.get("binary", cfg.codex.binary)
    cfg.codex.code_root = codex.get("code_root", cfg.codex.code_root)
    cfg.codex.sandbox = codex.get("sandbox", cfg.codex.sandbox)
    cfg.codex.json = bool(codex.get("json", cfg.codex.json))
    cfg.codex.start_prompt = codex.get("start_prompt", cfg.codex.start_prompt)
    cfg.codex.model = codex.get("model", cfg.codex.model)
    cfg.codex.model_reasoning_effort = codex.get("model_reasoning_effort", cfg.codex.model_reasoning_effort)
    cfg.codex.env = dict(codex.get("env", cfg.codex.env) or {})

    state = raw.get("state", {}) or {}
    cfg.state.data_dir = state.get("data_dir", cfg.state.data_dir)
    cfg.state.lock_timeout_seconds = int(state.get("lock_timeout_seconds", cfg.state.lock_timeout_seconds))
    cfg.state.conflict_ttl_seconds = int(state.get("conflict_ttl_seconds", cfg.state.conflict_ttl_seconds))
    cfg.state.log_dir = state.get("log_dir", cfg.state.log_dir)

    runtime = raw.get("runtime", {}) or {}
    cfg.runtime.log_level = runtime.get("log_level", cfg.runtime.log_level)

    audit = raw.get("audit", {}) or {}
    cfg.audit.redact = bool(audit.get("redact", cfg.audit.redact))
    cfg.audit.redact_patterns = list(audit.get("redact_patterns", cfg.audit.redact_patterns) or [])

    files = raw.get("files", {}) or {}
    cfg.files.max_upload_mb = int(files.get("max_upload_mb", cfg.files.max_upload_mb))

    transport = raw.get("transport", {}) or {}
    cfg.transport.adapter = transport.get("adapter", cfg.transport.adapter)

    repo_bootstrap = raw.get("repo_bootstrap", {}) or {}
    cfg.repo_bootstrap.agents_template = repo_bootstrap.get(
        "agents_template", cfg.repo_bootstrap.agents_template
    )
    cfg.repo_bootstrap.spec_prompt = repo_bootstrap.get("spec_prompt", cfg.repo_bootstrap.spec_prompt)


def _apply_defaults(cfg: Config) -> None:
    """Fill missing values with defaults."""
    if not cfg.discord.token_env:
        cfg.discord.token_env = DEFAULT_TOKEN_ENV
    if not cfg.discord.prefix:
        cfg.discord.prefix = DEFAULT_PREFIX
    if not cfg.discord.channel_name_regex:
        cfg.discord.channel_name_regex = DEFAULT_CHANNEL_REGEX
    if not cfg.discord.max_discord_message_chars:
        cfg.discord.max_discord_message_chars = DEFAULT_MAX_DISCORD_CHARS
    if not cfg.telegram.token_env:
        cfg.telegram.token_env = DEFAULT_TELEGRAM_TOKEN_ENV
    if not cfg.telegram.prefix:
        cfg.telegram.prefix = DEFAULT_PREFIX
    if not cfg.telegram.channel_name_regex:
        cfg.telegram.channel_name_regex = DEFAULT_CHANNEL_REGEX

    if not cfg.codex.binary:
        cfg.codex.binary = "codex"
    if not cfg.codex.sandbox:
        cfg.codex.sandbox = DEFAULT_SANDBOX
    if not cfg.codex.start_prompt:
        cfg.codex.start_prompt = DEFAULT_START_PROMPT
    if cfg.codex.env is None:
        cfg.codex.env = {}
    if not cfg.codex.json:
        cfg.codex.json = True

    if cfg.state.lock_timeout_seconds <= 0:
        cfg.state.lock_timeout_seconds = DEFAULT_LOCK_TIMEOUT_SECONDS
    if cfg.state.conflict_ttl_seconds <= 0:
        cfg.state.conflict_ttl_seconds = DEFAULT_CONFLICT_TTL_SECONDS
    if not cfg.runtime.log_level:
        cfg.runtime.log_level = DEFAULT_LOG_LEVEL
    cfg.audit.redact = bool(cfg.audit.redact)
    if cfg.files.max_upload_mb <= 0:
        cfg.files.max_upload_mb = DEFAULT_MAX_UPLOAD_MB
    if not cfg.transport.adapter:
        cfg.transport.adapter = DEFAULT_TRANSPORT_ADAPTER
    if not cfg.state.log_dir and cfg.state.data_dir:
        cfg.state.log_dir = os.path.join(cfg.state.data_dir, "logs")
    if not cfg.repo_bootstrap.spec_prompt:
        cfg.repo_bootstrap.spec_prompt = DEFAULT_SPEC_PROMPT


def _expand_paths(cfg: Config) -> None:
    """Expand env vars and ~ in configured paths."""
    cfg.codex.code_root = _expand_path(cfg.codex.code_root)
    cfg.state.data_dir = _expand_path(cfg.state.data_dir)
    cfg.state.log_dir = _expand_path(cfg.state.log_dir)
    cfg.repo_bootstrap.agents_template = _expand_path(cfg.repo_bootstrap.agents_template)


def _validate(cfg: Config) -> None:
    """Validate config values and required fields."""
    if not cfg.codex.code_root:
        raise ValueError("codex.code_root is required")
    if not cfg.state.data_dir:
        raise ValueError("state.data_dir is required")
    if not cfg.state.log_dir:
        raise ValueError("state.log_dir is required")
    if cfg.discord.max_discord_message_chars <= 0:
        raise ValueError("discord.max_discord_message_chars must be > 0")

    level = cfg.runtime.log_level.lower()
    if level not in {"debug", "info", "warn", "warning", "error"}:
        raise ValueError("runtime.log_level must be debug|info|warn|error")

    if cfg.transport.adapter.lower() not in {"discord", "slack", "telegram"}:
        raise ValueError("transport.adapter must be discord, slack, or telegram (additional adapters not yet supported)")
    if cfg.transport.adapter.lower() == "discord" and not (cfg.discord.guild_id or "").strip():
        raise ValueError("discord.guild_id is required when transport.adapter is discord")

    if len(cfg.discord.allowed_user_ids) == 0:
        if not cfg.discord.dm_admin_enabled or len(cfg.discord.dm_admin_user_ids) == 0:
            raise ValueError("discord.allowed_user_ids must list at least one user (or enable DM admin with dm_admin_user_ids)")
    if cfg.discord.totp_window < 0:
        raise ValueError("discord.totp_window must be >= 0")
    if cfg.discord.totp_enabled:
        env_name = (cfg.discord.totp_secret_env or "").strip()
        if not env_name:
            raise ValueError("discord.totp_secret_env is required when discord.totp_enabled is true")
        secret = os.getenv(env_name, "").strip()
        if not secret:
            raise ValueError(f"discord TOTP secret env {env_name!r} is empty")
    if cfg.transport.adapter.lower() == "telegram" and len(cfg.telegram.allowed_user_ids) == 0:
        raise ValueError("telegram.allowed_user_ids must list at least one user")

    try:
        cfg.discord._compiled_regex = re.compile(cfg.discord.channel_name_regex)
    except re.error as exc:
        raise ValueError(f"discord.channel_name_regex invalid: {exc}")
    try:
        cfg.telegram._compiled_regex = re.compile(cfg.telegram.channel_name_regex)
    except re.error as exc:
        raise ValueError(f"telegram.channel_name_regex invalid: {exc}")


_PERCENT_VAR_RE = re.compile(r"%([^%]+)%")


def _expand_path(val: str) -> str:
    """Expand $VAR, %VAR%, and ~ in path values."""
    if not val:
        return ""
    expanded = os.path.expandvars(val)
    expanded = _expand_percent_vars(expanded)
    if expanded.startswith("~"):
        expanded = os.path.join(os.path.expanduser("~"), expanded.lstrip("~"))
    return expanded


def _expand_percent_vars(val: str) -> str:
    """Expand Windows-style %VAR% tokens in a string."""
    def repl(match: re.Match) -> str:
        key = match.group(1)
        return os.getenv(key, match.group(0))

    return _PERCENT_VAR_RE.sub(repl, val)
