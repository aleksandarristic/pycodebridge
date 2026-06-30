"""Configuration loading and validation for the bridge."""

import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import yaml

from .util.coerce import parse_bool

DEFAULT_PREFIX = "!c"
DEFAULT_CHANNEL_REGEX = r"^code-([A-Za-z0-9._-]+)$"
DEFAULT_MAX_DISCORD_CHARS = 1800
DEFAULT_SANDBOX = "workspace-write"
DEFAULT_LOG_LEVEL = "info"
DEFAULT_TOKEN_ENV = "DISCORD_TOKEN"
DEFAULT_LOCK_TIMEOUT_SECONDS = 600
DEFAULT_CONFLICT_TTL_SECONDS = 60
DEFAULT_SESSION_IDLE_TTL_SECONDS = 14400
DEFAULT_TRANSPORT_ADAPTER = "discord"
DEFAULT_AUDIT_REDACT = False
DEFAULT_MAX_UPLOAD_MB = 200
DEFAULT_MAX_UPLOAD_TOTAL_MB = DEFAULT_MAX_UPLOAD_MB
DEFAULT_MAX_UPLOAD_COUNT = 20
DEFAULT_GIT_CREDENTIAL_HELPER = "!gh auth git-credential"

DEFAULT_WORKTREE_BASE_DIR = ""
DEFAULT_WORKTREE_MAX_PER_REPO = 8
DEFAULT_WORKTREE_CLEANUP_ON_END = "remove"

DEFAULT_DISPATCH_OUTPUT_MODE = "both"   # per_agent | aggregate | both
DEFAULT_DISPATCH_CLOSE_MODE = "pr"      # pr | merge
DEFAULT_DISPATCH_PLAN_PROMPT = (
    "You are the orchestrator for a multi-agent coding session.\n"
    "Analyse the user request below and produce a concise implementation plan.\n"
    "The plan will be passed as context to the other agents that will implement it.\n"
    "Keep the plan clear and actionable.\n\n"
    "User request: {{USER_REQUEST}}\n\n"
    "Agents that will implement the plan: {{AGENTS}}\n"
)

DEFAULT_START_PROMPT = (
    "Discord bridge session for {{REPO_NAME}}. Work only in this repo and keep replies concise.\n"
)

DEFAULT_SPEC_PROMPT = (
    "For {{REPO_NAME}}, ask for the project spec.\n"
    "When finalized, write `instructions/spec.md`, create `instructions/tasks/pending.md` with numbered tasks, "
    "append a milestone to `instructions/progress_log.md`, and summarize results concisely.\n"
)

DEFAULT_DM_ASSISTANT_START_PROMPT = (
    "You are the pycodebridge assistant. You have access to the pycodebridge repo at {{REPO_PATH}}. "
    "Answer questions about the bridge configuration, running sessions, and managed repos. "
    "Read docs on demand as needed."
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
    totp_max_failures: int = 5
    totp_failure_window_seconds: int = 300
    totp_cooldown_seconds: int = 300
    totp_enforce_git: bool = True
    totp_enforce_gh: bool = True
    totp_enforce_high_risk: bool = True
    totp_enforce_file_transfer: bool = True

    _compiled_regex: Optional[re.Pattern] = field(default=None, init=False, repr=False)


@dataclass
class CodexConfig:
    """Codex CLI configuration."""
    binary: str = "codex"
    code_root: str = ""
    sandbox: str = DEFAULT_SANDBOX
    ask_for_approval: str = ""
    network_access: bool = False
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
    session_idle_ttl_seconds: int = DEFAULT_SESSION_IDLE_TTL_SECONDS
    log_dir: str = ""


@dataclass
class RuntimeConfig:
    """Runtime logging configuration."""
    log_level: str = DEFAULT_LOG_LEVEL
    health_bind: str = ""
    health_allow_public: bool = False
    health_path: str = "/healthz"
    run_heartbeat_seconds: int = 120
    run_completion_min_seconds: int = 300
    show_reasoning_details: bool = True
    show_tool_calls: bool = True
    output_flush_seconds: float = 0.4


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
class GitConfig:
    """Git bootstrap configuration."""
    enabled: bool = False
    user_name: str = ""
    user_email: str = ""
    credential_helper: str = DEFAULT_GIT_CREDENTIAL_HELPER
    global_config_path: str = ""
    apply_on_startup: bool = True
    apply_to_existing_repos: bool = True
    apply_on_repo_create_clone_copy: bool = True
    local_fallback_on_global_failure: bool = True
    allow_dangerous_ops: bool = False
    require_confirmation_for_dangerous_ops: bool = True
    dangerous_confirmation_token: str = "--confirm-dangerous"


@dataclass
class FilesConfig:
    """File transfer configuration."""
    max_upload_mb: int = DEFAULT_MAX_UPLOAD_MB
    max_upload_total_mb: int = DEFAULT_MAX_UPLOAD_TOTAL_MB
    max_upload_count: int = DEFAULT_MAX_UPLOAD_COUNT


@dataclass
class RepoBootstrapConfig:
    """Repo bootstrap configuration for create/spec flows."""
    agents_template: str = ""
    agent_env_template: str = ""
    spec_prompt: str = DEFAULT_SPEC_PROMPT


@dataclass
class ClaudeConfig:
    """Claude Code CLI backend configuration."""
    binary: str = "claude"
    permission_mode: str = "default"
    model: str = ""
    effort: str = ""
    env: Dict[str, str] = field(default_factory=dict)


@dataclass
class GeminiConfig:
    """Gemini CLI backend configuration."""
    binary: str = "gemini"
    approval_mode: str = "yolo"  # default|auto_edit|yolo|plan
    model: str = ""
    api_key_env: str = ""
    env: Dict[str, str] = field(default_factory=dict)


@dataclass
class WorktreeConfig:
    """Git worktree isolation configuration."""
    enabled: bool = False
    session_isolation: bool = False
    base_dir: str = DEFAULT_WORKTREE_BASE_DIR
    max_per_repo: int = DEFAULT_WORKTREE_MAX_PER_REPO
    cleanup_on_end: str = DEFAULT_WORKTREE_CLEANUP_ON_END
    symlink_dirs: list = field(default_factory=lambda: [".venv", "node_modules"])


@dataclass
class DispatchConfig:
    """Multi-agent dispatch configuration."""
    output_mode: str = DEFAULT_DISPATCH_OUTPUT_MODE   # per_agent | aggregate | both
    close_mode: str = DEFAULT_DISPATCH_CLOSE_MODE     # pr | merge
    plan_prompt: str = DEFAULT_DISPATCH_PLAN_PROMPT   # template for orchestrator planning step


@dataclass
class AgentConfig:
    """Agent backend configuration."""
    default_backend: str = "codex"


@dataclass
class DmAssistantConfig:
    """LLM-powered DM assistant configuration."""
    enabled: bool = False
    default_backend: str = ""
    model: str = ""
    effort: str = ""
    memory_dir: str = ""
    start_prompt: str = DEFAULT_DM_ASSISTANT_START_PROMPT


@dataclass
class Config:
    """Top-level configuration container."""
    discord: DiscordConfig = field(default_factory=DiscordConfig)
    codex: CodexConfig = field(default_factory=CodexConfig)
    claude: ClaudeConfig = field(default_factory=ClaudeConfig)
    gemini: GeminiConfig = field(default_factory=GeminiConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    state: StateConfig = field(default_factory=StateConfig)
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)
    audit: AuditConfig = field(default_factory=AuditConfig)
    transport: TransportConfig = field(default_factory=TransportConfig)
    git: GitConfig = field(default_factory=GitConfig)
    files: FilesConfig = field(default_factory=FilesConfig)
    repo_bootstrap: RepoBootstrapConfig = field(default_factory=RepoBootstrapConfig)
    worktrees: WorktreeConfig = field(default_factory=WorktreeConfig)
    dispatch: DispatchConfig = field(default_factory=DispatchConfig)
    dm_assistant: DmAssistantConfig = field(default_factory=DmAssistantConfig)

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
        _ = platform
        return self.channel_regex()


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
    cfg.discord.allow_plain_prompts = _coerce_bool(
        discord.get("allow_plain_prompts", cfg.discord.allow_plain_prompts),
        "discord.allow_plain_prompts",
    )
    cfg.discord.dm_admin_enabled = _coerce_bool(
        discord.get("dm_admin_enabled", cfg.discord.dm_admin_enabled),
        "discord.dm_admin_enabled",
    )
    cfg.discord.dm_admin_user_ids = list(discord.get("dm_admin_user_ids", cfg.discord.dm_admin_user_ids) or [])
    totp = discord.get("totp", {}) or {}
    limiter = totp.get("limiter", {}) or {}
    command_groups = totp.get("command_groups", {}) or {}
    cfg.discord.totp_enabled = _coerce_bool(
        totp.get("enabled", discord.get("totp_enabled", cfg.discord.totp_enabled)),
        "discord.totp.enabled",
    )
    cfg.discord.totp_secret_env = totp.get(
        "secret_env",
        discord.get("totp_secret_env", cfg.discord.totp_secret_env),
    )
    cfg.discord.totp_window = int(totp.get("window", discord.get("totp_window", cfg.discord.totp_window)))
    cfg.discord.totp_max_failures = int(
        limiter.get("max_failures", discord.get("totp_max_failures", cfg.discord.totp_max_failures))
    )
    cfg.discord.totp_failure_window_seconds = int(
        limiter.get(
            "failure_window_seconds",
            discord.get("totp_failure_window_seconds", cfg.discord.totp_failure_window_seconds),
        )
    )
    cfg.discord.totp_cooldown_seconds = int(
        limiter.get("cooldown_seconds", discord.get("totp_cooldown_seconds", cfg.discord.totp_cooldown_seconds))
    )
    cfg.discord.totp_enforce_git = _coerce_bool(
        command_groups.get("git", discord.get("totp_enforce_git", cfg.discord.totp_enforce_git)),
        "discord.totp.command_groups.git",
    )
    cfg.discord.totp_enforce_gh = _coerce_bool(
        command_groups.get("gh", discord.get("totp_enforce_gh", cfg.discord.totp_enforce_gh)),
        "discord.totp.command_groups.gh",
    )
    cfg.discord.totp_enforce_high_risk = _coerce_bool(
        command_groups.get(
            "high_risk",
            discord.get("totp_enforce_high_risk", cfg.discord.totp_enforce_high_risk),
        ),
        "discord.totp.command_groups.high_risk",
    )
    cfg.discord.totp_enforce_file_transfer = _coerce_bool(
        command_groups.get(
            "file_transfer",
            discord.get("totp_enforce_file_transfer", cfg.discord.totp_enforce_file_transfer),
        ),
        "discord.totp.command_groups.file_transfer",
    )

    codex = raw.get("codex", {}) or {}
    cfg.codex.binary = codex.get("binary", cfg.codex.binary)
    cfg.codex.code_root = codex.get("code_root", cfg.codex.code_root)
    cfg.codex.sandbox = codex.get("sandbox", cfg.codex.sandbox)
    cfg.codex.ask_for_approval = codex.get("ask_for_approval", cfg.codex.ask_for_approval)
    cfg.codex.network_access = _coerce_bool(
        codex.get("network_access", cfg.codex.network_access),
        "codex.network_access",
    )
    cfg.codex.json = _coerce_bool(
        codex.get("json", cfg.codex.json),
        "codex.json",
    )
    cfg.codex.start_prompt = codex.get("start_prompt", cfg.codex.start_prompt)
    cfg.codex.model = codex.get("model", cfg.codex.model)
    cfg.codex.model_reasoning_effort = codex.get("model_reasoning_effort", cfg.codex.model_reasoning_effort)
    cfg.codex.env = dict(codex.get("env", cfg.codex.env) or {})

    claude = raw.get("claude", {}) or {}
    cfg.claude.binary = claude.get("binary", cfg.claude.binary)
    cfg.claude.permission_mode = claude.get("permission_mode", cfg.claude.permission_mode)
    cfg.claude.model = claude.get("model", cfg.claude.model)
    cfg.claude.effort = claude.get("effort", cfg.claude.effort)
    cfg.claude.env = dict(claude.get("env", cfg.claude.env) or {})

    gemini = raw.get("gemini", {}) or {}
    cfg.gemini.binary = gemini.get("binary", cfg.gemini.binary)
    cfg.gemini.approval_mode = gemini.get("approval_mode", cfg.gemini.approval_mode)
    cfg.gemini.model = gemini.get("model", cfg.gemini.model)
    cfg.gemini.api_key_env = str(gemini.get("api_key_env", cfg.gemini.api_key_env) or "").strip()
    cfg.gemini.env = dict(gemini.get("env", cfg.gemini.env) or {})

    agent = raw.get("agent", {}) or {}
    cfg.agent.default_backend = agent.get("default_backend", cfg.agent.default_backend)

    state = raw.get("state", {}) or {}
    cfg.state.data_dir = state.get("data_dir", cfg.state.data_dir)
    cfg.state.lock_timeout_seconds = int(state.get("lock_timeout_seconds", cfg.state.lock_timeout_seconds))
    cfg.state.conflict_ttl_seconds = int(state.get("conflict_ttl_seconds", cfg.state.conflict_ttl_seconds))
    cfg.state.session_idle_ttl_seconds = int(
        state.get("session_idle_ttl_seconds", cfg.state.session_idle_ttl_seconds)
    )
    cfg.state.log_dir = state.get("log_dir", cfg.state.log_dir)

    runtime = raw.get("runtime", {}) or {}
    cfg.runtime.log_level = runtime.get("log_level", cfg.runtime.log_level)
    cfg.runtime.health_bind = str(runtime.get("health_bind", cfg.runtime.health_bind) or "")
    cfg.runtime.health_allow_public = _coerce_bool(
        runtime.get("health_allow_public", cfg.runtime.health_allow_public),
        "runtime.health_allow_public",
    )
    cfg.runtime.health_path = str(runtime.get("health_path", cfg.runtime.health_path) or "")
    cfg.runtime.run_heartbeat_seconds = int(
        runtime.get("run_heartbeat_seconds", cfg.runtime.run_heartbeat_seconds)
    )
    cfg.runtime.run_completion_min_seconds = int(
        runtime.get("run_completion_min_seconds", cfg.runtime.run_completion_min_seconds)
    )
    cfg.runtime.show_reasoning_details = _coerce_bool(
        runtime.get("show_reasoning_details", cfg.runtime.show_reasoning_details),
        "runtime.show_reasoning_details",
    )
    cfg.runtime.show_tool_calls = _coerce_bool(
        runtime.get("show_tool_calls", cfg.runtime.show_tool_calls),
        "runtime.show_tool_calls",
    )
    cfg.runtime.output_flush_seconds = max(
        0.0, float(runtime.get("output_flush_seconds", cfg.runtime.output_flush_seconds))
    )

    audit = raw.get("audit", {}) or {}
    cfg.audit.redact = _coerce_bool(
        audit.get("redact", cfg.audit.redact),
        "audit.redact",
    )
    cfg.audit.redact_patterns = list(audit.get("redact_patterns", cfg.audit.redact_patterns) or [])

    files = raw.get("files", {}) or {}
    cfg.files.max_upload_mb = int(files.get("max_upload_mb", cfg.files.max_upload_mb))
    cfg.files.max_upload_total_mb = int(files.get("max_upload_total_mb", cfg.files.max_upload_total_mb))
    cfg.files.max_upload_count = int(files.get("max_upload_count", cfg.files.max_upload_count))

    transport = raw.get("transport", {}) or {}
    cfg.transport.adapter = transport.get("adapter", cfg.transport.adapter)

    git = raw.get("git", {}) or {}
    cfg.git.enabled = _coerce_bool(
        git.get("enabled", cfg.git.enabled),
        "git.enabled",
    )
    cfg.git.user_name = git.get("user_name", cfg.git.user_name)
    cfg.git.user_email = git.get("user_email", cfg.git.user_email)
    cfg.git.credential_helper = git.get("credential_helper", cfg.git.credential_helper)
    cfg.git.global_config_path = git.get("global_config_path", cfg.git.global_config_path)
    cfg.git.apply_on_startup = _coerce_bool(
        git.get("apply_on_startup", cfg.git.apply_on_startup),
        "git.apply_on_startup",
    )
    cfg.git.apply_to_existing_repos = _coerce_bool(
        git.get("apply_to_existing_repos", cfg.git.apply_to_existing_repos),
        "git.apply_to_existing_repos",
    )
    cfg.git.apply_on_repo_create_clone_copy = _coerce_bool(
        git.get("apply_on_repo_create_clone_copy", cfg.git.apply_on_repo_create_clone_copy),
        "git.apply_on_repo_create_clone_copy",
    )
    cfg.git.local_fallback_on_global_failure = _coerce_bool(
        git.get("local_fallback_on_global_failure", cfg.git.local_fallback_on_global_failure),
        "git.local_fallback_on_global_failure",
    )
    cfg.git.allow_dangerous_ops = _coerce_bool(
        git.get("allow_dangerous_ops", cfg.git.allow_dangerous_ops),
        "git.allow_dangerous_ops",
    )
    cfg.git.require_confirmation_for_dangerous_ops = _coerce_bool(
        git.get("require_confirmation_for_dangerous_ops", cfg.git.require_confirmation_for_dangerous_ops),
        "git.require_confirmation_for_dangerous_ops",
    )
    cfg.git.dangerous_confirmation_token = str(
        git.get("dangerous_confirmation_token", cfg.git.dangerous_confirmation_token)
    )

    repo_bootstrap = raw.get("repo_bootstrap", {}) or {}
    cfg.repo_bootstrap.agents_template = repo_bootstrap.get(
        "agents_template", cfg.repo_bootstrap.agents_template
    )
    cfg.repo_bootstrap.agent_env_template = repo_bootstrap.get(
        "agent_env_template", cfg.repo_bootstrap.agent_env_template
    )
    cfg.repo_bootstrap.spec_prompt = repo_bootstrap.get("spec_prompt", cfg.repo_bootstrap.spec_prompt)

    worktrees = raw.get("worktrees", {}) or {}
    cfg.worktrees.enabled = _coerce_bool(
        worktrees.get("enabled", cfg.worktrees.enabled),
        "worktrees.enabled",
    )
    cfg.worktrees.session_isolation = _coerce_bool(
        worktrees.get("session_isolation", cfg.worktrees.session_isolation),
        "worktrees.session_isolation",
    )
    cfg.worktrees.base_dir = str(worktrees.get("base_dir", cfg.worktrees.base_dir) or "")
    cfg.worktrees.max_per_repo = int(worktrees.get("max_per_repo", cfg.worktrees.max_per_repo))
    cfg.worktrees.cleanup_on_end = str(
        worktrees.get("cleanup_on_end", cfg.worktrees.cleanup_on_end) or DEFAULT_WORKTREE_CLEANUP_ON_END
    )
    raw_symlink = worktrees.get("symlink_dirs")
    if isinstance(raw_symlink, list):
        cfg.worktrees.symlink_dirs = [str(d) for d in raw_symlink if d]

    dispatch = raw.get("dispatch", {}) or {}
    cfg.dispatch.output_mode = str(
        dispatch.get("output_mode", cfg.dispatch.output_mode) or DEFAULT_DISPATCH_OUTPUT_MODE
    )
    cfg.dispatch.close_mode = str(
        dispatch.get("close_mode", cfg.dispatch.close_mode) or DEFAULT_DISPATCH_CLOSE_MODE
    )
    cfg.dispatch.plan_prompt = str(
        dispatch.get("plan_prompt", cfg.dispatch.plan_prompt) or DEFAULT_DISPATCH_PLAN_PROMPT
    )

    dm_assistant = raw.get("dm_assistant", {}) or {}
    cfg.dm_assistant.enabled = _coerce_bool(
        dm_assistant.get("enabled", cfg.dm_assistant.enabled),
        "dm_assistant.enabled",
    )
    cfg.dm_assistant.default_backend = str(
        dm_assistant.get("default_backend", cfg.dm_assistant.default_backend) or ""
    )
    cfg.dm_assistant.model = str(dm_assistant.get("model", cfg.dm_assistant.model) or "")
    cfg.dm_assistant.effort = str(dm_assistant.get("effort", cfg.dm_assistant.effort) or "")
    cfg.dm_assistant.memory_dir = str(dm_assistant.get("memory_dir", cfg.dm_assistant.memory_dir) or "")
    cfg.dm_assistant.start_prompt = str(
        dm_assistant.get("start_prompt", cfg.dm_assistant.start_prompt) or DEFAULT_DM_ASSISTANT_START_PROMPT
    )


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
    cfg.discord.totp_enforce_git = _coerce_bool(cfg.discord.totp_enforce_git, "discord.totp.command_groups.git")
    cfg.discord.totp_enforce_gh = _coerce_bool(cfg.discord.totp_enforce_gh, "discord.totp.command_groups.gh")
    cfg.discord.totp_enforce_high_risk = _coerce_bool(
        cfg.discord.totp_enforce_high_risk,
        "discord.totp.command_groups.high_risk",
    )
    cfg.discord.totp_enforce_file_transfer = _coerce_bool(
        cfg.discord.totp_enforce_file_transfer,
        "discord.totp.command_groups.file_transfer",
    )
    if not cfg.codex.binary:
        cfg.codex.binary = "codex"
    if not cfg.codex.sandbox:
        cfg.codex.sandbox = DEFAULT_SANDBOX
    if cfg.codex.ask_for_approval is None:
        cfg.codex.ask_for_approval = ""
    cfg.codex.network_access = _coerce_bool(cfg.codex.network_access, "codex.network_access")
    if not cfg.codex.start_prompt:
        cfg.codex.start_prompt = DEFAULT_START_PROMPT
    if cfg.codex.env is None:
        cfg.codex.env = {}
    if not cfg.codex.json:
        cfg.codex.json = True
    if not cfg.claude.binary:
        cfg.claude.binary = "claude"
    if not cfg.claude.permission_mode:
        cfg.claude.permission_mode = "default"
    if cfg.claude.env is None:
        cfg.claude.env = {}
    if not cfg.gemini.binary:
        cfg.gemini.binary = "gemini"
    if not cfg.gemini.approval_mode:
        cfg.gemini.approval_mode = "yolo"
    if cfg.gemini.api_key_env is None:
        cfg.gemini.api_key_env = ""
    if cfg.gemini.env is None:
        cfg.gemini.env = {}
    if not cfg.agent.default_backend:
        cfg.agent.default_backend = "codex"

    if cfg.state.lock_timeout_seconds <= 0:
        cfg.state.lock_timeout_seconds = DEFAULT_LOCK_TIMEOUT_SECONDS
    if cfg.state.conflict_ttl_seconds <= 0:
        cfg.state.conflict_ttl_seconds = DEFAULT_CONFLICT_TTL_SECONDS
    if cfg.state.session_idle_ttl_seconds < 0:
        cfg.state.session_idle_ttl_seconds = DEFAULT_SESSION_IDLE_TTL_SECONDS
    if not cfg.runtime.log_level:
        cfg.runtime.log_level = DEFAULT_LOG_LEVEL
    if not cfg.runtime.health_path:
        cfg.runtime.health_path = "/healthz"
    if not cfg.runtime.health_path.startswith("/"):
        cfg.runtime.health_path = "/" + cfg.runtime.health_path
    if cfg.runtime.run_heartbeat_seconds <= 0:
        cfg.runtime.run_heartbeat_seconds = 120
    if cfg.runtime.run_completion_min_seconds <= 0:
        cfg.runtime.run_completion_min_seconds = 300
    cfg.runtime.show_reasoning_details = _coerce_bool(cfg.runtime.show_reasoning_details, "runtime.show_reasoning_details")
    cfg.runtime.show_tool_calls = _coerce_bool(cfg.runtime.show_tool_calls, "runtime.show_tool_calls")
    cfg.audit.redact = _coerce_bool(cfg.audit.redact, "audit.redact")
    if cfg.files.max_upload_mb <= 0:
        cfg.files.max_upload_mb = DEFAULT_MAX_UPLOAD_MB
    if cfg.files.max_upload_total_mb <= 0:
        cfg.files.max_upload_total_mb = DEFAULT_MAX_UPLOAD_TOTAL_MB
    if cfg.files.max_upload_count <= 0:
        cfg.files.max_upload_count = DEFAULT_MAX_UPLOAD_COUNT
    if not cfg.transport.adapter:
        cfg.transport.adapter = DEFAULT_TRANSPORT_ADAPTER
    if cfg.git.credential_helper is None:
        cfg.git.credential_helper = DEFAULT_GIT_CREDENTIAL_HELPER
    if not cfg.git.dangerous_confirmation_token:
        cfg.git.dangerous_confirmation_token = "--confirm-dangerous"
    if not cfg.state.log_dir and cfg.state.data_dir:
        cfg.state.log_dir = os.path.join(cfg.state.data_dir, "logs")
    if not cfg.repo_bootstrap.spec_prompt:
        cfg.repo_bootstrap.spec_prompt = DEFAULT_SPEC_PROMPT
    cfg.worktrees.enabled = _coerce_bool(cfg.worktrees.enabled, "worktrees.enabled")
    cfg.worktrees.session_isolation = _coerce_bool(
        cfg.worktrees.session_isolation,
        "worktrees.session_isolation",
    )
    if not cfg.worktrees.cleanup_on_end:
        cfg.worktrees.cleanup_on_end = DEFAULT_WORKTREE_CLEANUP_ON_END
    if not cfg.dispatch.output_mode:
        cfg.dispatch.output_mode = DEFAULT_DISPATCH_OUTPUT_MODE
    if not cfg.dispatch.close_mode:
        cfg.dispatch.close_mode = DEFAULT_DISPATCH_CLOSE_MODE
    if not cfg.dispatch.plan_prompt:
        cfg.dispatch.plan_prompt = DEFAULT_DISPATCH_PLAN_PROMPT
    if not cfg.dm_assistant.start_prompt:
        cfg.dm_assistant.start_prompt = DEFAULT_DM_ASSISTANT_START_PROMPT


def _expand_paths(cfg: Config) -> None:
    """Expand env vars and ~ in configured paths."""
    cfg.codex.code_root = _expand_path(cfg.codex.code_root)
    cfg.state.data_dir = _expand_path(cfg.state.data_dir)
    cfg.state.log_dir = _expand_path(cfg.state.log_dir)
    cfg.git.global_config_path = _expand_path(cfg.git.global_config_path)
    cfg.repo_bootstrap.agents_template = _expand_path(cfg.repo_bootstrap.agents_template)
    cfg.repo_bootstrap.agent_env_template = _expand_path(cfg.repo_bootstrap.agent_env_template)
    cfg.worktrees.base_dir = _expand_path(cfg.worktrees.base_dir)
    cfg.dm_assistant.memory_dir = _expand_path(cfg.dm_assistant.memory_dir)


def _coerce_bool(value: Any, field: str) -> bool:
    """Parse a strict boolean from bool/int/string values."""
    try:
        return parse_bool(value)
    except ValueError as exc:
        raise ValueError(f"{field} must be a boolean") from exc


def _validate(cfg: Config) -> None:
    """Validate config values and required fields."""
    if not cfg.codex.code_root:
        raise ValueError("codex.code_root is required")
    if not cfg.state.data_dir:
        raise ValueError("state.data_dir is required")
    if not cfg.state.log_dir:
        raise ValueError("state.log_dir is required")
    approval = (cfg.codex.ask_for_approval or "").strip().lower()
    if approval and approval not in {"untrusted", "on-failure", "on-request", "never"}:
        raise ValueError("codex.ask_for_approval must be untrusted|on-failure|on-request|never")
    cfg.codex.ask_for_approval = approval
    if cfg.discord.max_discord_message_chars <= 0:
        raise ValueError("discord.max_discord_message_chars must be > 0")

    cleanup = (cfg.worktrees.cleanup_on_end or "").strip().lower()
    if cleanup not in {"remove", "keep", "pr"}:
        raise ValueError("worktrees.cleanup_on_end must be remove|keep|pr")
    cfg.worktrees.cleanup_on_end = cleanup
    if cfg.worktrees.max_per_repo < 1 or cfg.worktrees.max_per_repo > 64:
        raise ValueError("worktrees.max_per_repo must be between 1 and 64")

    output_mode = (cfg.dispatch.output_mode or "").strip().lower()
    if output_mode not in {"per_agent", "aggregate", "both"}:
        raise ValueError("dispatch.output_mode must be per_agent|aggregate|both")
    cfg.dispatch.output_mode = output_mode
    close_mode = (cfg.dispatch.close_mode or "").strip().lower()
    if close_mode not in {"pr", "merge"}:
        raise ValueError("dispatch.close_mode must be pr|merge")
    cfg.dispatch.close_mode = close_mode

    level = cfg.runtime.log_level.lower()
    if level not in {"debug", "info", "warn", "warning", "error"}:
        raise ValueError("runtime.log_level must be debug|info|warn|error")
    if cfg.runtime.run_heartbeat_seconds < 1 or cfg.runtime.run_heartbeat_seconds > 86400:
        raise ValueError("runtime.run_heartbeat_seconds must be between 1 and 86400")
    if cfg.runtime.run_completion_min_seconds < 1 or cfg.runtime.run_completion_min_seconds > 86400:
        raise ValueError("runtime.run_completion_min_seconds must be between 1 and 86400")
    if cfg.state.session_idle_ttl_seconds < 0 or cfg.state.session_idle_ttl_seconds > 31536000:
        raise ValueError("state.session_idle_ttl_seconds must be between 0 and 31536000")

    if cfg.transport.adapter.lower() != "discord":
        raise ValueError("transport.adapter must be discord")
    if not (cfg.discord.guild_id or "").strip():
        raise ValueError("discord.guild_id is required when transport.adapter is discord")

    if len(cfg.discord.allowed_user_ids) == 0:
        raise ValueError("discord.allowed_user_ids must list at least one user")
    if cfg.discord.totp_window < 0:
        raise ValueError("discord.totp_window must be >= 0")
    if cfg.discord.totp_max_failures < 0:
        raise ValueError("discord.totp_max_failures must be >= 0")
    if cfg.discord.totp_failure_window_seconds <= 0:
        raise ValueError("discord.totp_failure_window_seconds must be > 0")
    if cfg.discord.totp_cooldown_seconds < 0:
        raise ValueError("discord.totp_cooldown_seconds must be >= 0")
    if cfg.discord.totp_enabled:
        env_name = (cfg.discord.totp_secret_env or "").strip()
        if not env_name:
            raise ValueError("discord.totp_secret_env is required when discord.totp_enabled is true")
        secret = os.getenv(env_name, "").strip()
        if not secret:
            raise ValueError(f"discord TOTP secret env {env_name!r} is empty")
    try:
        cfg.discord._compiled_regex = re.compile(cfg.discord.channel_name_regex)
    except re.error as exc:
        raise ValueError(f"discord.channel_name_regex invalid: {exc}")


_PERCENT_VAR_RE = re.compile(r"%([^%]+)%")


def _expand_path(val: str) -> str:
    """Expand $VAR, %VAR%, and ~ in path values."""
    if not val:
        return ""
    expanded = os.path.expandvars(val)
    expanded = _expand_percent_vars(expanded)
    expanded = os.path.expanduser(expanded)
    return expanded


def _expand_percent_vars(val: str) -> str:
    """Expand Windows-style %VAR% tokens in a string."""
    def repl(match: re.Match) -> str:
        key = match.group(1)
        return os.getenv(key, match.group(0))

    return _PERCENT_VAR_RE.sub(repl, val)
