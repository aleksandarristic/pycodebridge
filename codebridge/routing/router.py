"""Codex command router and handlers."""

import asyncio
import contextlib
import os
import re
import shlex
import subprocess
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Set
import json
import tempfile
import zipfile

from .. import config as cfgmod
from ..observability.audit import Entry, Logger as AuditLogger
from ..observability.audit_helpers import AuditHelper
from ..observability.session_jsonl import SessionJsonlHelper, SessionJsonlLogger
from ..codex import Event, Options, Runner, display_texts, parse_event
from ..sessions.coordinator import SessionCoordinator
from ..sessions.state import Store, utc_now_iso
from ..platform.transport import MessageEvent, ResponseSink, null_typing
from ..util import path as pathutil
from ..handlers import core as core_handlers
from ..handlers import dm_admin as dm_admin_handlers
from ..handlers import gh_helpers as gh_handlers
from ..handlers import git_helpers as git_handlers
from ..handlers import repo_helpers as repo_handlers
from ..handlers import system_helpers
from ..commands import registry as command_registry
from ..commands.parse import parse_session_quit_alias, parse_session_slash_prompt
from ..commands.shortcuts import normalize_bang_shortcut
from ..services.file_transfer import FileTransferService
from .reply import send_forbidden, send_reply
from ..util.ansi import strip_control_codes
from ..util.chunk import chunk_text
from ..util.coerce import parse_bool
from ..util.prompt import needs_user_input
from ..util.session_artifacts import safe_segment, session_artifact_label
from ..security.totp import TotpAttemptLimiter, verify_totp
from ..services import git_bootstrap
from ..commands import help as help_renderer
from .helpers import (
    DEFAULT_SESSION,
    MAX_SESSIONS_PER_CHANNEL,
    PendingConflict,
    UsageStats,
    normalize_session,
    normalize_thread_session_name,
    usage_from_event,
)
from .config import render_config_text
from .status import format_current_selection_line, format_session_line
from .event_context import build_contextual_sink, normalize_event_context

_TOTP_ARG_RE = re.compile(r"(?:^|\s)--totp\s+(\d{6})(?=\s|$)")
_AWAITING_INPUT_TTL_SECONDS = 900
_DEFAULT_UNLOCK_SECONDS = 3600
_UNLOCK_TTL_RE = re.compile(r"^(\d+)\s*([mhd])$", re.IGNORECASE)
_UNLOCK_STATUS_TOKENS = {"status", "state"}
_UNLOCK_SCOPE_DEFAULT = "default"
_UNLOCK_SCOPE_GH = "gh"
_RESET_ALL_CONFIRM_TTL_SECONDS = 30
_DISCORD_LEADING_MENTION_RE = re.compile(r"^(?:<@!?\d+>\s*)+")
_READ_ONLY_COMMANDS = {
    "budget",
    "branch",
    "help",
    "health",
    "status",
    "stats",
    "peek",
    "models",
    "updates",
    "show",
    "changes",
    "ps",
}
_RUN_HEARTBEAT_SECONDS = 120
_RUN_COMPLETION_MIN_SECONDS = 300
_RUN_KEY_RESULT_MAX = 180
_RUNTIME_OPTION_KEYS = ("run_heartbeat_seconds", "run_completion_min_seconds", "show_reasoning_details")


def _git_commit_hash() -> str:
    try:
        root = Path(__file__).resolve().parents[2]
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(root),
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except Exception:
        return "unknown"

class Router:
    """Main command router for Discord messages."""
    def __init__(self, cfg: cfgmod.Config, state: Store, audit: AuditLogger, runner: Runner, coordinator: SessionCoordinator, logger):
        self.cfg = cfg
        self.state = state
        self.audit = audit
        self.runner = runner
        self.logger = logger
        self._usage: Dict[str, Dict[str, UsageStats]] = {}
        self.coordinator = coordinator
        self._command_registry, self._command_specs = command_registry.build_registry()
        self.file_transfers = FileTransferService(cfg, logger)
        self._commit = _git_commit_hash()
        self._audit_helper = AuditHelper(audit, logger)
        session_logger = None
        if self.cfg.state.log_dir:
            try:
                session_logger = SessionJsonlLogger(self.cfg.state.log_dir)
            except Exception as exc:
                self.logger.warning("session_jsonl.init_failed", extra={"error": str(exc)})
        self._session_log = SessionJsonlHelper(session_logger, logger)
        self._awaiting_input: Dict[str, Dict[str, float]] = {}
        self._totp_last_step_by_user: Dict[str, int] = {}
        self._totp_locked_users: Set[str] = set()
        self._totp_unlock_until: Dict[str, float] = {}
        self._reset_all_confirm_until: Dict[str, float] = {}
        self._totp_limiter = TotpAttemptLimiter(
            max_failures=cfg.discord.totp_max_failures,
            window_seconds=cfg.discord.totp_failure_window_seconds,
            cooldown_seconds=cfg.discord.totp_cooldown_seconds,
        )
        self._codex_error_log_path = os.path.join(self.cfg.state.log_dir, "codex_errors.log") if self.cfg.state.log_dir else ""
        self._budget_usage_channel: Dict[str, int] = {}
        self._budget_usage_user: Dict[str, int] = {}
        self._budget_thresholds_channel: Dict[str, tuple[int, int]] = {}
        self._budget_thresholds_user: Dict[str, tuple[int, int]] = {}
        self._runtime_defaults = {
            "run_heartbeat_seconds": max(1, min(86400, int(getattr(self.cfg.runtime, "run_heartbeat_seconds", _RUN_HEARTBEAT_SECONDS)))),
            "run_completion_min_seconds": max(
                1, min(86400, int(getattr(self.cfg.runtime, "run_completion_min_seconds", _RUN_COMPLETION_MIN_SECONDS)))
            ),
            "show_reasoning_details": bool(getattr(self.cfg.runtime, "show_reasoning_details", True)),
        }
        self._runtime_options_global: Dict[str, Any] = {}
        self._runtime_options_channels: Dict[str, Dict[str, Any]] = {}
        self._load_runtime_options_from_state()

    async def handle_message(self, event: MessageEvent, sink: ResponseSink) -> None:
        """Handle an incoming message event."""
        if event.author_is_bot:
            return
        event = normalize_event_context(event)
        await self._migrate_legacy_thread_scope(event)
        lock_emoji = ""
        if self._totp_enabled(event):
            lock_emoji = "🔓" if self._totp_is_unlocked(event, _UNLOCK_SCOPE_DEFAULT) else "🔒"
        sink = build_contextual_sink(event, sink, self.cfg.discord.max_discord_message_chars, lock_emoji)

        self.logger.info(
            "incoming.message",
            extra={
                "platform": event.platform,
                "channel_id": event.channel_id,
                "is_dm": event.is_dm,
                "user_id": event.author_id,
            },
        )

        channel_name = event.channel_name or event.channel_id

        if event.is_dm:
            await dm_admin_handlers.handle_dm_message(self, event, sink)
            return
        if event.platform == "discord" and not self._discord_repo_channel_is_private(event):
            self.logger.info(
                "routing.skip_non_private_channel",
                extra={"channel_id": event.channel_id, "guild_id": event.guild_id, "user_id": event.author_id},
            )
            return
        if event.platform == "discord" and not event.guild_id:
            await self.reply_forbidden(sink, "This bot only works in guild channels.")
            return

        if event.platform == "discord" and self.cfg.discord.guild_id and event.guild_id != self.cfg.discord.guild_id:
            await self.reply_forbidden(sink, "This bot is not configured for this guild.")
            return

        if not self._transport_user_allowed(event):
            await self.reply_forbidden(sink, "You are not allowed to use this bot.")
            return

        rexp = self.cfg.channel_regex_for(event.platform)
        match = rexp.match(channel_name)
        if not match:
            return

        try:
            repo_name = pathutil.normalize_repo_name(match.group(1))
        except ValueError as exc:
            await self.reply_forbidden(sink, f"Repo error: {exc}")
            return
        prefix = self._transport_prefix(event)
        content = (event.content or "").strip()
        had_leading_mention = False
        if event.platform == "discord":
            content, had_leading_mention = self._strip_discord_leading_mention(content)
            if had_leading_mention and not content:
                return
        shortcut_cmdline = self._shortcut_cmdline(content)
        if await self._handle_attachment_flow(event, sink, repo_name, content):
            return
        handled_pending, _ = await self._handle_pending_upload_flow(event, sink, repo_name, content)
        if handled_pending:
            return
        if await self._handle_plain_prompt_flow(
            event,
            sink,
            repo_name,
            prefix,
            content,
            shortcut_cmdline,
            had_leading_mention,
        ):
            return
        await self._handle_command_flow(event, sink, repo_name, prefix, content, shortcut_cmdline)

    async def _repo_path_or_forbidden(self, sink: ResponseSink, repo_name: str, *, for_create: bool = False) -> str | None:
        try:
            if for_create:
                return pathutil.resolve_repo_path_for_create(self.cfg.codex.code_root, repo_name)
            return pathutil.resolve_repo_path(self.cfg.codex.code_root, repo_name)
        except Exception as exc:
            await self.reply_forbidden(sink, f"Repo error: {exc}")
            return None

    async def _handle_attachment_flow(self, event: MessageEvent, sink: ResponseSink, repo_name: str, content: str) -> bool:
        if not event.attachments:
            return False
        if self._totp_enabled(event):
            ok, _ = await self.require_totp(event, sink, "upload", content)
            if not ok:
                return True
        repo_path = await self._repo_path_or_forbidden(sink, repo_name)
        if repo_path is None:
            return True
        await self.handle_upload_request(event, sink, repo_name, repo_path)
        return True

    async def _handle_pending_upload_flow(
        self,
        event: MessageEvent,
        sink: ResponseSink,
        repo_name: str,
        content: str,
    ) -> tuple[bool, str]:
        pending_content = content
        if self.file_transfers.has_pending_upload(event) and self._totp_enabled(event):
            ok, pending_content = await self.require_totp(event, sink, "upload", content)
            if not ok:
                return True, pending_content
        handled = await self.handle_pending_upload_response(event, sink, repo_name, pending_content)
        return handled, pending_content

    async def _handle_plain_prompt_flow(
        self,
        event: MessageEvent,
        sink: ResponseSink,
        repo_name: str,
        prefix: str,
        content: str,
        shortcut_cmdline: str,
        had_leading_mention: bool,
    ) -> bool:
        if had_leading_mention and event.platform_thread_id and not content.startswith(prefix) and not shortcut_cmdline:
            # In Discord threads, require explicit command syntax after a bot mention.
            return True
        if content.startswith(prefix) or shortcut_cmdline:
            return False

        relay_session, ambiguous = await self.pending_input_session(event)
        if ambiguous:
            await self.reply_forbidden(
                sink,
                "Multiple sessions are waiting for input. Use `!c answer <session> -- <text>`.",
            )
            return True
        if relay_session:
            relay_text = content.strip()
            if not relay_text:
                return True
            if self._totp_enabled(event) and not self._totp_is_unlocked(event):
                ok, relay_text = await self.require_totp(event, sink, "answer", relay_text)
                if not ok:
                    return True
            await self.handle_answer(event, sink, relay_session, relay_text)
            return True
        pending_session = self.current_session_for_event(event)
        pending_conflict = await self.consume_pending(event.channel_id, pending_session)
        if pending_conflict is not None:
            pending_conflict.prompt = content.strip() or (pending_conflict.prompt or "").strip()
            await self.coordinator.set_pending_conflict(event.channel_id, pending_conflict.session, pending_conflict)
            repo_path = await self._repo_path_or_forbidden(sink, repo_name)
            if repo_path is None:
                return True
            await self.handle_choose(event, sink, repo_name, repo_path, pending_conflict.session, "new")
            return True
        allow_plain = self._transport_allow_plain_prompts(event)
        if self._totp_enabled(event) and self._totp_is_unlocked(event):
            allow_plain = True
        if not allow_plain:
            return True
        self.logger.info(
            "routing.prompt",
            extra={
                "platform": event.platform,
                "channel_id": event.channel_id,
                "repo": repo_name,
                "session": self.current_session_for_event(event),
            },
        )
        prompt = content.strip()
        if not prompt:
            return True
        if self._totp_enabled(event) and not self._totp_is_unlocked(event):
            ok, prompt = await self.require_totp(event, sink, "resume", prompt)
            if not ok:
                return True
        repo_path = await self._repo_path_or_forbidden(sink, repo_name)
        if repo_path is None:
            return True
        session = self.current_session_for_event(event)
        await self.handle_resume(event, sink, repo_name, repo_path, session, prompt)
        return True

    async def _handle_command_flow(
        self,
        event: MessageEvent,
        sink: ResponseSink,
        repo_name: str,
        prefix: str,
        content: str,
        shortcut_cmdline: str,
    ) -> None:
        if shortcut_cmdline:
            cmdline = shortcut_cmdline
        else:
            cmdline = content[len(prefix) :].strip()
        if not cmdline:
            return
        cmdline = self._normalize_unlock_totp_syntax(cmdline)

        handled_pending, _ = await self._handle_pending_upload_flow(event, sink, repo_name, cmdline)
        if handled_pending:
            return

        fields = cmdline.split()
        cmd = fields[0].lower()
        rest = cmdline[len(fields[0]) :].strip()
        canonical_cmd = self._canonical_command(cmd)
        effective_cmd = "/quit" if len(fields) >= 2 and fields[1] == "/quit" else cmd
        if self._totp_enabled(event) and self._totp_required_for_command(event, effective_cmd, rest):
            ok, cmdline = await self.require_totp(event, sink, effective_cmd, cmdline)
            if not ok:
                return
            fields = cmdline.split()
            if not fields:
                return
            cmd = fields[0].lower()
            rest = cmdline[len(fields[0]) :].strip()
            canonical_cmd = self._canonical_command(cmd)
            effective_cmd = "/quit" if len(fields) >= 2 and fields[1] == "/quit" else cmd
        self.logger.info(
            "routing.command",
            extra={
                "platform": event.platform,
                "channel_id": event.channel_id,
                "repo": repo_name,
                "cmd": cmd,
                "session": self.current_session_for_event(event),
                "user_id": event.author_id,
            },
        )
        if canonical_cmd == "create":
            repo_path = await self._repo_path_or_forbidden(sink, repo_name, for_create=True)
            if repo_path is None:
                return
            await self.handle_create_repo(event, sink, repo_name, repo_path)
            return

        repo_path = await self._repo_path_or_forbidden(sink, repo_name)
        if repo_path is None:
            return

        quit_session = parse_session_quit_alias(fields)
        if quit_session:
            session_name = quit_session
            try:
                session_name = normalize_session(session_name)
            except ValueError as exc:
                await self.reply_forbidden(sink, str(exc))
                return
            await self.handle_quit(sink, session_name)
            return
        slash_session, slash_prompt = parse_session_slash_prompt(cmdline)
        if slash_session:
            session_name = slash_session
            try:
                session_name = normalize_session(session_name)
            except ValueError as exc:
                await self.reply_forbidden(sink, str(exc))
                return
            await self.handle_resume(event, sink, repo_name, repo_path, session_name, slash_prompt)
            return

        if await command_registry.dispatch(
            self._command_registry,
            self,
            event,
            sink,
            repo_name,
            repo_path,
            cmd,
            rest,
        ):
            return

        await self.handle_resume(event, sink, repo_name, repo_path, self.current_session_for_event(event), cmdline)

    async def handle_dm_message(self, event: MessageEvent, sink: ResponseSink) -> None:
        """Handle an incoming DM admin message."""
        await dm_admin_handlers.handle_dm_message(self, event, sink)

    async def _migrate_legacy_thread_scope(self, event: MessageEvent) -> None:
        """Rekey legacy Discord thread scope to canonical room key when needed."""
        if event.platform != "discord" or event.is_dm or not event.platform_thread_id:
            return
        legacy_channel_id = event.platform_thread_id
        canonical_channel_id = event.channel_id
        if not legacy_channel_id or not canonical_channel_id or legacy_channel_id == canonical_channel_id:
            return
        changed = await self.coordinator.migrate_channel_scope(legacy_channel_id, canonical_channel_id)
        if not self._move_channel_runtime_maps(legacy_channel_id, canonical_channel_id):
            if not changed:
                return
        self.logger.info(
            "routing.thread_scope_rekey",
            extra={
                "legacy_channel_id": legacy_channel_id,
                "canonical_channel_id": canonical_channel_id,
                "thread_id": event.platform_thread_id,
            },
        )

    def _move_channel_runtime_maps(self, from_channel_id: str, to_channel_id: str) -> bool:
        """Move router runtime channel maps to a canonical key."""
        if not from_channel_id or not to_channel_id or from_channel_id == to_channel_id:
            return False
        changed = False

        from_usage = self._usage.pop(from_channel_id, None)
        if from_usage is not None:
            target_usage = self._usage.setdefault(to_channel_id, {})
            for session, stats in from_usage.items():
                if session not in target_usage:
                    target_usage[session] = stats
            changed = True

        from_pending = self._awaiting_input.pop(from_channel_id, None)
        if from_pending is not None:
            target_pending = self._awaiting_input.setdefault(to_channel_id, {})
            for session, expires_at in from_pending.items():
                if session not in target_pending:
                    target_pending[session] = expires_at
            changed = True

        from_budget_usage = self._budget_usage_channel.pop(from_channel_id, None)
        if from_budget_usage is not None:
            self._budget_usage_channel[to_channel_id] = self._budget_usage_channel.get(to_channel_id, 0) + from_budget_usage
            changed = True

        from_budget_thresholds = self._budget_thresholds_channel.pop(from_channel_id, None)
        if from_budget_thresholds is not None:
            self._budget_thresholds_channel.setdefault(to_channel_id, from_budget_thresholds)
            changed = True

        from_runtime_opts = self._runtime_options_channels.pop(from_channel_id, None)
        if from_runtime_opts is not None:
            target_runtime_opts = self._runtime_options_channels.setdefault(to_channel_id, {})
            for key, value in from_runtime_opts.items():
                if key not in target_runtime_opts:
                    target_runtime_opts[key] = value
            changed = True
        return changed

    def _strip_discord_leading_mention(self, content: str) -> tuple[str, bool]:
        """Strip one or more leading Discord mention tokens."""
        raw = (content or "").strip()
        if not raw:
            return "", False
        match = _DISCORD_LEADING_MENTION_RE.match(raw)
        if not match:
            return raw, False
        remainder = raw[match.end() :].lstrip(" \t,;:-")
        return remainder, True

    def _shortcut_cmdline(self, content: str) -> str:
        """Translate top-level !<command> forms into canonical command lines."""
        return normalize_bang_shortcut(content, self._command_registry.keys())

    async def handle_start(self, event: MessageEvent, sink: ResponseSink, repo_name: str, repo_path: str, session: str) -> None:
        """Start a new Codex session for a channel/session."""
        await core_handlers.handle_start(self, event, sink, repo_name, repo_path, session)

    async def handle_resume(
        self,
        event: MessageEvent,
        sink: ResponseSink,
        repo_name: str,
        repo_path: str,
        session: str,
        prompt: str,
        skip_idle_ttl_check: bool = False,
    ) -> None:
        """Resume a Codex session with a prompt."""
        await core_handlers.handle_resume(
            self,
            event,
            sink,
            repo_name,
            repo_path,
            session,
            prompt,
            skip_idle_ttl_check=skip_idle_ttl_check,
        )

    async def handle_create_repo(self, event: MessageEvent, sink: ResponseSink, repo_name: str, repo_path: str) -> None:
        """Create a new repo directory and git init."""
        await core_handlers.handle_create_repo(self, event, sink, repo_name, repo_path)

    async def handle_clone_repo(
        self,
        event: MessageEvent,
        sink: ResponseSink,
        repo_name: str,
        repo_path: str,
        raw_url: str,
    ) -> None:
        """Clone a GitHub repo into code_root for the channel name."""
        await core_handlers.handle_clone_repo(self, event, sink, repo_name, repo_path, raw_url)

    async def handle_copy_repo(
        self,
        event: MessageEvent,
        sink: ResponseSink,
        repo_name: str,
        repo_path: str,
        new_name: str,
        target_path: str,
    ) -> None:
        """Copy an existing repo into a new directory without .git."""
        await core_handlers.handle_copy_repo(self, event, sink, repo_name, repo_path, new_name, target_path)

    async def handle_spec(
        self,
        event: MessageEvent,
        sink: ResponseSink,
        repo_name: str,
        repo_path: str,
        session: str,
    ) -> None:
        """Run the spec capture flow via Codex."""
        await core_handlers.handle_spec(self, event, sink, repo_name, repo_path, session)

    async def handle_choose(
        self,
        event: MessageEvent,
        sink: ResponseSink,
        repo_name: str,
        repo_path: str,
        session: str,
        choice: str,
    ) -> None:
        """Resolve a pending start conflict."""
        await core_handlers.handle_choose(self, event, sink, repo_name, repo_path, session, choice)

    async def handle_stop(self, sink: ResponseSink, session: str) -> None:
        """Send a stop signal to a running Codex process."""
        await core_handlers.handle_stop(self, sink, session)

    async def handle_interrupt(self, sink: ResponseSink, session: str) -> None:
        """Send an interrupt signal to a running Codex process."""
        await core_handlers.handle_interrupt(self, sink, session)

    async def handle_kill(self, sink: ResponseSink, session: str) -> None:
        """Force-kill a running Codex process."""
        await core_handlers.handle_kill(self, sink, session)

    async def handle_quit(self, sink: ResponseSink, session: str) -> None:
        """Send /quit to the Codex process."""
        await core_handlers.handle_quit(self, sink, session)

    async def handle_answer(self, event: MessageEvent, sink: ResponseSink, session: str, text: str) -> None:
        """Send an approval/input response to an active Codex session."""
        await core_handlers.handle_answer(self, event, sink, session, text)

    async def handle_steer(self, event: MessageEvent, sink: ResponseSink, session: str, text: str) -> None:
        """Send steering text to an active Codex session."""
        await core_handlers.handle_steer(self, event, sink, session, text)

    async def handle_wait(self, event: MessageEvent, sink: ResponseSink) -> None:
        """Show sessions currently awaiting user input from Codex prompts."""
        pending = self._prune_awaiting_input(event.channel_id)
        if not pending:
            await self.reply(sink, self._with_related("No sessions are waiting for input.", "!ps", "!c status"))
            return
        active: list[str] = []
        for session in sorted(pending.keys()):
            if await self.get_active(event.channel_id, session):
                active.append(session)
        if not active:
            await self.reply(sink, self._with_related("No active sessions are waiting for input.", "!ps", "!c status"))
            return
        await self.reply(sink, self._with_related("Waiting for input: " + ", ".join(active), "!c answer", "!a <text>"))

    async def handle_showrepo(self, sink: ResponseSink, repo_path: str) -> None:
        """Show a pruned repo tree for orientation."""
        await repo_handlers.handle_showrepo(self, sink, repo_path)

    async def handle_showchanges(self, sink: ResponseSink, repo_path: str) -> None:
        """Show git status and diffstat for the repo."""
        await repo_handlers.handle_showchanges(self, sink, repo_path)

    async def handle_tests(self, sink: ResponseSink, repo_path: str) -> None:
        """Run tests for the repo (pytest -q)."""
        await repo_handlers.handle_tests(self, sink, repo_path)

    async def handle_git(self, sink: ResponseSink, repo_path: str, rest: str) -> None:
        """Run safe git helper commands."""
        await git_handlers.handle_git(self, sink, repo_path, rest)

    async def handle_branch(self, sink: ResponseSink, repo_path: str) -> None:
        """Show current git branch and clean/not-clean state."""
        await git_handlers.handle_branch(self, sink, repo_path)

    async def handle_gh(self, sink: ResponseSink, repo_path: str, rest: str) -> None:
        """Run gh helper commands."""
        await gh_handlers.handle_gh(self, sink, repo_path, rest)

    async def handle_download(self, sink: ResponseSink, repo_path: str, rel_path: str) -> None:
        """Send a file from the repo to the channel."""
        await self.file_transfers.handle_download(sink, repo_path, rel_path, self.reply_forbidden)

    async def bootstrap_git_config(self) -> None:
        """Apply startup git bootstrap settings."""
        await git_bootstrap.bootstrap_startup(self.cfg, self.logger)

    async def bootstrap_repo_git_config(self, repo_path: str) -> None:
        """Apply git bootstrap settings to a repo local config when configured."""
        if not self.cfg.git.enabled or not self.cfg.git.apply_on_repo_create_clone_copy:
            return
        await git_bootstrap.apply_repo_local(self.cfg, self.logger, repo_path)

    async def handle_updates(self, sink: ResponseSink, repo_path: str) -> None:
        """Check installed Codex CLI version against npm latest."""
        await system_helpers.handle_updates(self, sink, repo_path)

    async def handle_health(self, sink: ResponseSink, repo_path: str) -> None:
        """Show runtime diagnostics for the bridge."""
        await system_helpers.handle_health(self, sink, repo_path)

    async def handle_options(self, event: MessageEvent, sink: ResponseSink, rest: str) -> None:
        """Show or mutate mutable runtime options."""
        raw = (rest or "").strip()
        if not raw or self._options_show_requested(raw):
            await self.reply(sink, self._runtime_options_text(sink.channel_id, event.is_dm))
            return
        parts = raw.split()
        action = parts[0].lower()
        if action != "set" or len(parts) < 3:
            await self.reply_forbidden(
                sink,
                self._options_usage_hint(event.is_dm),
            )
            return
        key = parts[1].strip().lower()
        scope = "local"
        value_parts = parts[2:]
        if event.is_dm and len(value_parts) >= 2 and value_parts[-1].lower() in {"local", "global"}:
            scope = value_parts[-1].lower()
            value_parts = value_parts[:-1]
        elif (not event.is_dm) and len(value_parts) >= 2 and value_parts[-1].lower() in {"local", "global"}:
            await self.reply_forbidden(
                sink,
                "Scope is only supported in DM. Channel commands always use local scope.\n"
                "Try: `!c options set run_heartbeat_seconds 120`",
            )
            return
        value = " ".join(value_parts).strip()
        if not value:
            await self.reply_forbidden(sink, self._options_usage_hint(event.is_dm))
            return
        key_aliases = {
            "run_heartbeat_seconds": "run_heartbeat_seconds",
            "heartbeat": "run_heartbeat_seconds",
            "runtime.run_heartbeat_seconds": "run_heartbeat_seconds",
            "run_completion_min_seconds": "run_completion_min_seconds",
            "completion": "run_completion_min_seconds",
            "runtime.run_completion_min_seconds": "run_completion_min_seconds",
            "show_reasoning_details": "show_reasoning_details",
            "reasoning_details": "show_reasoning_details",
            "show_reasoning": "show_reasoning_details",
            "runtime.show_reasoning_details": "show_reasoning_details",
        }
        canonical = key_aliases.get(key)
        if not canonical:
            await self.reply_forbidden(
                sink,
                "Unknown option key.\n"
                f"Allowed keys: {', '.join(_RUNTIME_OPTION_KEYS)}\n"
                "Use `!c options` to see current values and examples.",
            )
            return
        if canonical in {"run_heartbeat_seconds", "run_completion_min_seconds"}:
            try:
                parsed = int(value)
            except ValueError:
                await self.reply_forbidden(
                    sink,
                    f"Invalid integer value for {canonical}: {value!r}\n"
                    "Expected an integer between 1 and 86400.\n"
                    "Example: `!c options set run_heartbeat_seconds 120`",
                )
                return
            if parsed < 1 or parsed > 86400:
                await self.reply_forbidden(
                    sink,
                    f"{canonical} must be between 1 and 86400.\n"
                    "Example: `!c options set run_completion_min_seconds 300`",
                )
                return
            self._set_runtime_option(scope, sink.channel_id, canonical, parsed)
            await self.reply(
                sink,
                f"Runtime option updated: {canonical}={parsed} (scope: {scope}, persisted).",
            )
            return
        bool_true = {"1", "true", "yes", "on"}
        bool_false = {"0", "false", "no", "off"}
        token = value.lower()
        bool_value: Optional[bool]
        if token in bool_true:
            bool_value = True
        elif token in bool_false:
            bool_value = False
        else:
            await self.reply_forbidden(
                sink,
                f"Invalid boolean value for {canonical}: {value!r}. Use true/false.\n"
                "Examples: `true`, `false`, `on`, `off`, `1`, `0`.",
            )
            return
        self._set_runtime_option(scope, sink.channel_id, canonical, bool_value)
        await self.reply(
            sink,
            f"Runtime option updated: {canonical}={bool_value} (scope: {scope}, persisted).",
        )

    async def handle_budget(self, event: MessageEvent, sink: ResponseSink, rest: str) -> None:
        """Show or mutate usage budget settings."""
        parts = (rest or "").strip().split()
        if not parts or parts[0].lower() == "status":
            await self.reply(sink, self._budget_status_text(event))
            return
        action = parts[0].lower()
        if action == "set":
            if len(parts) != 4:
                await self.reply_forbidden(sink, "Usage: !c budget set channel <soft> <hard> | !c budget set user <soft> <hard>")
                return
            scope = parts[1].lower()
            try:
                soft = int(parts[2])
                hard = int(parts[3])
            except ValueError:
                await self.reply_forbidden(sink, "Budget thresholds must be integers.")
                return
            if soft < 0 or hard < 0 or (hard and soft > hard):
                await self.reply_forbidden(sink, "Invalid thresholds. Use non-negative ints and soft <= hard.")
                return
            if scope == "channel":
                self._budget_thresholds_channel[event.channel_id] = (soft, hard)
            elif scope == "user":
                self._budget_thresholds_user[self._budget_user_key(event)] = (soft, hard)
            else:
                await self.reply_forbidden(sink, "Scope must be `channel` or `user`.")
                return
            await self.reply(sink, f"Budget {scope} thresholds set: soft={soft}, hard={hard}.")
            return
        if action == "clear":
            scope = parts[1].lower() if len(parts) >= 2 else "all"
            if scope not in {"channel", "user", "all"}:
                await self.reply_forbidden(sink, "Usage: !c budget clear [channel|user|all]")
                return
            if scope in {"channel", "all"}:
                self._budget_thresholds_channel.pop(event.channel_id, None)
            if scope in {"user", "all"}:
                self._budget_thresholds_user.pop(self._budget_user_key(event), None)
            await self.reply(sink, f"Budget thresholds cleared for {scope}.")
            return
        await self.reply_forbidden(sink, "Usage: !c budget [status] | !c budget set ... | !c budget clear ...")

    async def handle_logs(self, sink: ResponseSink, session: str, limit: int) -> None:
        """Show recent audit log entries."""
        try:
            summaries = self.audit.summaries(sink.channel_id, session, limit)
        except Exception as exc:
            await self.reply(sink, f"logs error: {exc}")
            return
        if not summaries:
            await self.reply(sink, "No logs yet.")
            return
        lines = []
        for s in summaries:
            started = s.started_at or "n/a"
            ended = s.ended_at or "n/a"
            lines.append(
                f"[{s.seq}] channel:{s.channel_id} session:{s.session} thread:{s.thread_id} "
                f"started:{started} ended:{ended}"
            )
        text = "\n".join(lines)
        for chunk in chunk_text(text, self.cfg.discord.max_discord_message_chars):
            await self.reply(sink, chunk)

    async def handle_audit_list(self, sink: ResponseSink, session: str, limit: int) -> None:
        """Show audit summaries with request command context."""
        try:
            summaries = self.audit.summaries(sink.channel_id, session, limit)
        except Exception as exc:
            await self.reply(sink, f"audit error: {exc}")
            return
        if not summaries:
            await self.reply(sink, "No audit entries found.")
            return
        lines = []
        for s in summaries:
            req = s.request or {}
            cmd = str(req.get("command") or "").strip() or "?"
            args = str(req.get("args") or "").strip()
            lines.append(
                f"[{s.seq}] session:{s.session} thread:{s.thread_id} cmd:{cmd} args:{args} started:{s.started_at or 'n/a'}"
            )
        await self.reply(sink, "\n".join(lines))

    async def handle_audit_find(self, sink: ResponseSink, term: str, limit: int) -> None:
        """Filter audit entries for current channel by term."""
        query = (term or "").strip().lower()
        if not query:
            await self.reply_forbidden(sink, "Search term required.")
            return
        try:
            summaries = self.audit.summaries(sink.channel_id, "", max(limit * 5, limit))
        except Exception as exc:
            await self.reply(sink, f"audit error: {exc}")
            return
        filtered = []
        for s in summaries:
            req = s.request or {}
            hay = " ".join(
                [
                    s.seq,
                    s.session,
                    s.thread_id,
                    str(req.get("command") or ""),
                    str(req.get("args") or ""),
                    str(req.get("timestamp") or ""),
                ]
            ).lower()
            if query in hay:
                filtered.append(s)
            if len(filtered) >= limit:
                break
        if not filtered:
            await self.reply(sink, f"No audit matches for `{term}`.")
            return
        lines = [f"Audit matches for `{term}`:"]
        for s in filtered:
            req = s.request or {}
            lines.append(
                f"- [{s.seq}] session:{s.session} cmd:{req.get('command') or '?'} args:{req.get('args') or ''}"
            )
        await self.reply(sink, "\n".join(lines))

    async def handle_audit_show(self, sink: ResponseSink, seq: str) -> None:
        """Show one audit entry in detail."""
        summary = self._audit_find_summary_by_seq(sink.channel_id, seq)
        if not summary:
            await self.reply_forbidden(sink, f"Audit entry `{seq}` not found.")
            return
        req = summary.request or {}
        lines = [
            f"Audit `{summary.seq}`",
            f"- Channel: {summary.channel_id}",
            f"- Session: {summary.session}",
            f"- Thread: {summary.thread_id}",
            f"- Command: {req.get('command') or 'n/a'}",
            f"- Args: {req.get('args') or ''}",
            f"- Started: {summary.started_at or 'n/a'}",
            f"- Ended: {summary.ended_at or 'n/a'}",
            f"- Path: {summary.path}",
        ]
        await self.reply(sink, "\n".join(lines))

    async def handle_audit_bundle(self, sink: ResponseSink, seq: str) -> None:
        """Bundle one audit entry artifacts into a zip and send it."""
        summary = self._audit_find_summary_by_seq(sink.channel_id, seq)
        if not summary:
            await self.reply_forbidden(sink, f"Audit entry `{seq}` not found.")
            return
        bundle_path = self._create_audit_bundle(summary)
        if not bundle_path:
            await self.reply_forbidden(sink, "Unable to create audit bundle.")
            return
        filename = f"audit-{summary.seq}.zip"
        try:
            await sink.send_file(bundle_path, filename)
        finally:
            try:
                os.remove(bundle_path)
            except Exception:
                pass
        await self.reply(sink, f"Audit bundle ready: `{filename}`")

    def _audit_find_summary_by_seq(self, channel_id: str, seq: str):
        token = (seq or "").strip()
        if not token:
            return None
        try:
            summaries = self.audit.summaries(channel_id, "", 500)
        except Exception:
            return None
        for s in summaries:
            if s.seq == token:
                return s
        return None

    def _create_audit_bundle(self, summary) -> str:
        seq = summary.seq
        thread_dir = summary.path
        files = [
            os.path.join(thread_dir, f"{seq}.request.json"),
            os.path.join(thread_dir, f"{seq}.codex.jsonl"),
            os.path.join(thread_dir, f"{seq}.discord_out.txt"),
            os.path.join(thread_dir, f"{seq}.codex.stderr.txt"),
        ]
        existing = [p for p in files if os.path.exists(p)]
        if not existing:
            return ""
        tmp = tempfile.NamedTemporaryFile(prefix=f"audit-{seq}-", suffix=".zip", delete=False)
        tmp.close()
        try:
            with zipfile.ZipFile(tmp.name, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                for path in existing:
                    zf.write(path, arcname=os.path.basename(path))
            return tmp.name
        except Exception:
            try:
                os.remove(tmp.name)
            except Exception:
                pass
            return ""

    async def handle_ps(self, sink: ResponseSink) -> None:
        """Show queued/running jobs for the channel."""
        statuses = await self.coordinator.snapshot(sink.channel_id)
        if not statuses:
            await self.reply_forbidden(sink, "No jobs queued or running.")
            return
        lines = []
        for s in statuses:
            pos = f" pos:{s.position}" if s.position >= 0 else ""
            queued_at = self._format_job_time(s.queued_at)
            started_at = self._format_job_time(s.started_at)
            ended_at = self._format_job_time(s.ended_at)
            lines.append(
                f"{s.job_id} [{s.status}] session:{s.session or DEFAULT_SESSION}{pos} "
                f"queued:{queued_at} started:{started_at} ended:{ended_at} {s.command}"
            )
        await self.reply(sink, "\n".join(lines))

    def _format_job_time(self, value: float) -> str:
        if not value:
            return "-"
        try:
            epoch = time.time() - (asyncio.get_running_loop().time() - value)
        except RuntimeError:
            epoch = time.time()
        try:
            return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()
        except Exception:
            return "-"

    async def handle_cancel(self, sink: ResponseSink, job_id: str) -> None:
        """Cancel a queued job by id."""
        ok = await self.coordinator.cancel(sink.channel_id, job_id)
        if not ok:
            await self.reply_forbidden(sink, "Unknown job id.")
            return
        await self.reply(sink, f"Cancelled job {job_id}.")

    async def handle_rerun(self, sink: ResponseSink) -> None:
        """Requeue the last job for the channel."""
        job_id = await self.coordinator.rerun(sink.channel_id)
        if not job_id:
            await self.reply_forbidden(sink, "No prior job to rerun.")
            return
        await self.reply(sink, f"Requeued job {job_id}.")

    async def handle_unlock(self, event: MessageEvent, sink: ResponseSink, rest: str) -> None:
        """Unlock TOTP scopes for this user account on the current platform."""
        try:
            action, scope, value = self._parse_unlock_action(rest)
        except ValueError as exc:
            await self.reply_forbidden(sink, str(exc))
            return
        if action == "status":
            await self._reply_unlock_status(event, sink, scope)
            return
        if action == "extend":
            try:
                ttl_seconds = self._parse_unlock_ttl_seconds(value)
            except ValueError as exc:
                await self.reply_forbidden(sink, str(exc))
                return
            await self._extend_unlock_window(event, sink, scope, ttl_seconds)
            return
        try:
            ttl_seconds = self._parse_unlock_ttl_seconds(value)
        except ValueError as exc:
            await self.reply_forbidden(sink, str(exc))
            return
        if scope == "all":
            self._set_totp_unlock(event, _UNLOCK_SCOPE_DEFAULT, ttl_seconds)
            self._set_totp_unlock(event, _UNLOCK_SCOPE_GH, ttl_seconds)
            await self.reply(
                sink,
                f"TOTP unlock active for {self._format_duration(ttl_seconds)} for your account (default + gh). "
                "High-risk commands still require --totp.",
            )
            return
        self._set_totp_unlock(event, scope, ttl_seconds)
        if scope == _UNLOCK_SCOPE_GH:
            await self.reply(
                sink,
                f"TOTP gh unlock active for {self._format_duration(ttl_seconds)} for your account.",
            )
            return
        await self.reply(
            sink,
            f"TOTP unlock active for {self._format_duration(ttl_seconds)} for your account. "
            "High-risk commands still require --totp.",
        )

    async def handle_lock(self, event: MessageEvent, sink: ResponseSink, rest: str = "") -> None:
        """Handle lock command actions (clear, status, extend)."""
        try:
            action, scope, ttl_seconds = self._parse_lock_action(rest)
        except ValueError as exc:
            await self.reply_forbidden(sink, str(exc))
            return
        if action == "status":
            await self._reply_unlock_status(event, sink, scope)
            return
        if action == "extend":
            assert ttl_seconds is not None
            await self._extend_unlock_window(event, sink, scope, ttl_seconds)
            return
        if scope == "all":
            self._clear_totp_unlock(event, _UNLOCK_SCOPE_DEFAULT)
            self._clear_totp_unlock(event, _UNLOCK_SCOPE_GH)
            await self.reply(sink, "TOTP unlocks cleared for your account.")
            return
        self._clear_totp_unlock(event, scope)
        if scope == _UNLOCK_SCOPE_GH:
            await self.reply(sink, "TOTP gh unlock cleared for your account.")
            return
        await self.reply(sink, "TOTP unlock cleared for your account.")

    async def handle_select_session(self, event: MessageEvent, sink: ResponseSink, session: str) -> None:
        """Set the sticky session selection for a user."""
        user_id = event.author_id
        channel_id = event.channel_id
        if not event.is_dm:
            session = self.resolve_scoped_session_for_event(event, session)
        self.coordinator.set_sticky(channel_id, user_id, session)
        await self.update_state(channel_id, session, "", "", "", "", "")
        await self.reply(sink, f"Using session '{session}' by default.")
        await self.update_pinned_status(sink, user_id, session)

    async def handle_thread(self, sink: ResponseSink, session: str, repo_name: str, repo_path: str, thread_id: str) -> None:
        """Override stored thread id for a session."""
        session = normalize_session(session or DEFAULT_SESSION)
        self.update_state(sink.channel_id, session, repo_name, repo_path, thread_id, "", "")
        await self.reply(sink, f"Thread id for session '{session}' set to {thread_id}")

    async def handle_reset_session(self, sink: ResponseSink, channel_id: str, session: str) -> None:
        """Reset a session by clearing persisted context and session-local runtime state."""
        result = await self.control_reset_session(channel_id, session, purge=False)
        if result.get("blocked_running"):
            await self.reply_forbidden(
                sink,
                f"Session '{result['session']}' has a running non-interruptible job. Retry reset after it finishes.",
            )
            return
        details = []
        if result["removed"]:
            details.append("cleared stored context")
        else:
            details.append("no stored context was found")
        if result["killed"]:
            details.append("killed active process")
        if result["cancelled_jobs"]:
            details.append(f"cancelled {result['cancelled_jobs']} queued job(s)")
        await self.reply(sink, f"Session '{result['session']}' reset: {', '.join(details)}.")
        self.logger.info(
            "session.reset",
            extra={
                "channel_id": result["channel_id"],
                "session": result["session"],
                "removed": result["removed"],
                "killed": result["killed"],
                "cancelled_jobs": result["cancelled_jobs"],
            },
        )

    async def handle_purge_session(self, sink: ResponseSink, channel_id: str, session: str) -> None:
        """Purge a session by resetting state/runtime and removing session artifacts."""
        result = await self.control_reset_session(channel_id, session, purge=True)
        if result.get("blocked_running"):
            await self.reply_forbidden(
                sink,
                f"Session '{result['session']}' has a running non-interruptible job. Retry purge after it finishes.",
            )
            return
        details = []
        if result["removed"]:
            details.append("cleared stored context")
        else:
            details.append("no stored context was found")
        if result["killed"]:
            details.append("killed active process")
        if result["cancelled_jobs"]:
            details.append(f"cancelled {result['cancelled_jobs']} queued job(s)")
        details.append(f"removed {result['purged_artifacts']} session artifact(s)")
        await self.reply(sink, f"Session '{result['session']}' purged: {', '.join(details)}.")
        self.logger.info(
            "session.purge",
            extra={
                "channel_id": result["channel_id"],
                "session": result["session"],
                "removed": result["removed"],
                "killed": result["killed"],
                "cancelled_jobs": result["cancelled_jobs"],
                "purged_artifacts": result["purged_artifacts"],
            },
        )

    async def handle_purge_stale_sessions(self, event: MessageEvent, sink: ResponseSink, ttl_seconds: int) -> None:
        """Purge stale sessions older than TTL in the current scope channel key."""
        state = self.state.load()
        ch = state.channels.get(event.channel_id)
        if not ch or not ch.sessions:
            await self.reply(sink, "No sessions to purge.")
            return
        purged: list[str] = []
        skipped_running = 0
        purged_artifacts = 0
        for name in sorted(list(ch.sessions.keys())):
            sess = ch.sessions[name]
            idle = self._session_idle_seconds(sess.last_used_at or sess.created_at)
            if idle < 0 or idle < ttl_seconds:
                continue
            result = await self.control_reset_session(event.channel_id, name, purge=True)
            if result["blocked_running"]:
                skipped_running += 1
                continue
            if result["removed"]:
                purged.append(name)
            purged_artifacts += int(result["purged_artifacts"])
        if not purged and skipped_running == 0:
            await self.reply(sink, f"No sessions exceeded stale TTL {self._format_duration(ttl_seconds)}.")
            return
        msg = (
            f"Purged {len(purged)} stale session(s) older than {self._format_duration(ttl_seconds)}; "
            f"removed {purged_artifacts} artifact(s)."
        )
        if purged:
            msg += " Sessions: " + ", ".join(purged) + "."
        if skipped_running:
            msg += f" Skipped running: {skipped_running}."
        await self.reply(sink, msg)

    async def handle_session_lifecycle_status(self, event: MessageEvent, sink: ResponseSink) -> None:
        """Show session lifecycle status for the current channel."""
        state = self.state.load()
        ch = state.channels.get(event.channel_id)
        if not ch or not ch.sessions:
            await self.reply(sink, "No sessions tracked for this channel.")
            return
        lines = ["Session lifecycle status:"]
        for name in sorted(ch.sessions.keys()):
            sess = ch.sessions[name]
            idle = self._session_idle_seconds(sess.last_used_at or sess.created_at)
            idle_text = self._format_duration(int(idle)) if idle >= 0 else "unknown"
            proc = await self.get_active(event.channel_id, name)
            status = "running" if proc is not None else "idle"
            lines.append(
                f"- {name}: {status}, idle {idle_text}, repo {sess.repo_name or 'n/a'}, thread {sess.thread_id or 'n/a'}"
            )
        await self.reply(sink, "\n".join(lines))

    async def handle_session_lifecycle_prune(self, event: MessageEvent, sink: ResponseSink, ttl_seconds: int) -> None:
        """Prune idle sessions older than TTL for current channel."""
        state = self.state.load()
        ch = state.channels.get(event.channel_id)
        if not ch or not ch.sessions:
            await self.reply(sink, "No sessions to prune.")
            return
        removed: list[str] = []
        skipped_running = 0
        for name in sorted(list(ch.sessions.keys())):
            sess = ch.sessions[name]
            idle = self._session_idle_seconds(sess.last_used_at or sess.created_at)
            if idle < 0 or idle < ttl_seconds:
                continue
            if await self.get_active(event.channel_id, name) is not None:
                skipped_running += 1
                continue
            deleted = await self.coordinator.reset_session(event.channel_id, name)
            self.clear_awaiting_input(event.channel_id, name)
            if deleted:
                removed.append(name)
        if not removed and skipped_running == 0:
            await self.reply(sink, f"No sessions exceeded idle TTL {self._format_duration(ttl_seconds)}.")
            return
        msg = f"Pruned {len(removed)} session(s) older than {self._format_duration(ttl_seconds)}."
        if removed:
            msg += " Removed: " + ", ".join(removed) + "."
        if skipped_running:
            msg += f" Skipped running: {skipped_running}."
        await self.reply(sink, msg)

    async def handle_session_lifecycle_archive(
        self,
        event: MessageEvent,
        sink: ResponseSink,
        session: str,
        repo_name: str,
        repo_path: str,
    ) -> None:
        """Archive concise session summary for later restore."""
        state = self.state.load()
        ch = state.channels.get(event.channel_id)
        sess = ch.sessions.get(session) if ch else None
        if not sess:
            await self.reply_forbidden(sink, f"Session '{session}' not found.")
            return
        content = self._build_session_archive_text(event.channel_id, session, sess, repo_name or sess.repo_name, repo_path or sess.repo_path)
        archive_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        archive_dir = self._session_archive_dir(event.channel_id, session, repo_name or sess.repo_name)
        os.makedirs(archive_dir, exist_ok=True)
        path = os.path.join(archive_dir, f"{archive_id}.txt")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        await self.reply(sink, f"Archived session '{session}' as `{archive_id}`.")

    async def handle_session_lifecycle_restore(
        self,
        event: MessageEvent,
        sink: ResponseSink,
        session: str,
        repo_name: str,
        repo_path: str,
        archive_id: str,
    ) -> None:
        """Restore context by sending archived summary as prompt preface."""
        archive_repo = repo_name or self._session_repo_name(event.channel_id, session)
        archive_file = self._find_archive_file(event.channel_id, session, archive_repo, archive_id)
        if not archive_file:
            await self.reply_forbidden(sink, "Archive not found for that session.")
            return
        try:
            archived = Path(archive_file).read_text(encoding="utf-8")
        except Exception as exc:
            await self.reply_forbidden(sink, f"Archive read error: {exc}")
            return
        prompt = (
            "Session context archive loaded. Use this summary as prior context.\n\n"
            f"{archived}\n\n"
            "Continue from this state and ask for clarification when needed."
        )
        await self.handle_resume(event, sink, repo_name, repo_path, session, prompt)

    def _session_archive_dir(self, channel_id: str, session: str, repo_name: str = "") -> str:
        base = self.cfg.state.log_dir or tempfile.gettempdir()
        safe_channel = safe_segment(channel_id or "channel", "channel")
        label = session_artifact_label(repo_name, session or DEFAULT_SESSION)
        return os.path.join(base, "session_archives", safe_channel, label)

    def _find_archive_file(self, channel_id: str, session: str, repo_name: str, archive_id: str = "") -> str:
        dirs = [
            self._session_archive_dir(channel_id, session, repo_name),
            self._session_archive_dir(channel_id, session, ""),
            os.path.join(
                self.cfg.state.log_dir or tempfile.gettempdir(),
                "session_archives",
                safe_segment(channel_id or "channel", "channel"),
                safe_segment(session or DEFAULT_SESSION, "default"),
            ),
        ]
        if archive_id:
            for archive_dir in dirs:
                path = os.path.join(archive_dir, f"{archive_id}.txt")
                if os.path.exists(path):
                    return path
            return ""

        candidates: list[Path] = []
        for archive_dir in dirs:
            if not os.path.isdir(archive_dir):
                continue
            candidates.extend(Path(archive_dir).glob("*.txt"))
        candidates = sorted(set(candidates))
        if not candidates:
            return ""
        return str(candidates[-1])

    def _session_idle_seconds(self, timestamp: str) -> int:
        raw = (timestamp or "").strip()
        if not raw:
            return -1
        try:
            dt = datetime.strptime(raw, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except Exception:
            try:
                dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except Exception:
                return -1
        return max(0, int((datetime.now(timezone.utc) - dt).total_seconds()))

    def _build_session_archive_text(self, channel_id: str, session: str, sess: Any, repo_name: str, repo_path: str) -> str:
        lines = [
            f"Session: {session}",
            f"Repo: {repo_name or sess.repo_name or 'n/a'}",
            f"Repo path: {repo_path or sess.repo_path or 'n/a'}",
            f"Thread id: {sess.thread_id or 'n/a'}",
            f"Model: {sess.model or self.cfg.codex.model or 'default'}",
            f"Reasoning: {sess.reasoning_effort or self.cfg.codex.model_reasoning_effort or 'default'}",
            f"Created at: {sess.created_at or 'n/a'}",
            f"Last used: {sess.last_used_at or 'n/a'}",
        ]
        try:
            summaries = self.audit.summaries(channel_id, session, 1)
        except Exception:
            summaries = []
        if summaries:
            req = summaries[0].request or {}
            lines.append(f"Last request command: {req.get('command') or 'n/a'}")
            lines.append(f"Last request args: {req.get('args') or ''}".strip())
        return "\n".join(lines)

    async def handle_reset_all_sessions(self, sink: ResponseSink) -> None:
        """Reset all sessions across channels, cancelling queued work and killing active processes when possible."""
        snapshots = await self.coordinator.snapshot_all()
        status_by_key: dict[tuple[str, str], dict[str, object]] = {}
        for channel_id, statuses in snapshots.items():
            for st in statuses:
                key = (channel_id, st.session or DEFAULT_SESSION)
                entry = status_by_key.setdefault(key, {"queued_ids": [], "running": False})
                if st.status == "queued":
                    queued_ids = entry["queued_ids"]
                    assert isinstance(queued_ids, list)
                    queued_ids.append(st.job_id)
                elif st.status == "running":
                    entry["running"] = True

        state = self.state.load()
        targets: set[tuple[str, str]] = set(status_by_key.keys())
        for channel_id, ch in state.channels.items():
            for session in ch.sessions.keys():
                targets.add((channel_id, session or DEFAULT_SESSION))

        if not targets:
            await self.reply(sink, "Reset all sessions: no sessions, queued jobs, or running jobs were found.")
            return

        cancelled_jobs = 0
        killed_processes = 0
        removed_sessions = 0
        blocked_running = 0
        processed_sessions = 0

        for channel_id, session in sorted(targets):
            session = normalize_session(session or DEFAULT_SESSION)
            meta = status_by_key.get((channel_id, session), {"queued_ids": [], "running": False})
            queued_ids = list(meta.get("queued_ids", []))
            running_job = bool(meta.get("running", False))

            for job_id in queued_ids:
                if await self.coordinator.cancel(channel_id, job_id):
                    cancelled_jobs += 1

            proc = await self.get_active(channel_id, session)
            if proc is not None:
                await proc.kill()
                killed_processes += 1
            elif running_job:
                blocked_running += 1
                continue

            removed = await self.coordinator.reset_session(channel_id, session)
            self.clear_awaiting_input(channel_id, session)
            processed_sessions += 1
            if removed:
                removed_sessions += 1

        details = [
            f"cleared stored context for {removed_sessions} session(s)",
            f"killed {killed_processes} active process(es)",
            f"cancelled {cancelled_jobs} queued job(s)",
        ]
        if blocked_running:
            details.append(f"skipped {blocked_running} non-interruptible running session(s)")
        await self.reply(sink, "Reset all sessions: " + ", ".join(details) + ".")
        self.logger.info(
            "session.reset_all",
            extra={
                "targets": len(targets),
                "processed_sessions": processed_sessions,
                "removed_sessions": removed_sessions,
                "killed_processes": killed_processes,
                "cancelled_jobs": cancelled_jobs,
                "blocked_running": blocked_running,
            },
        )

    async def control_reset_session(self, channel_id: str, session: str, purge: bool = False) -> dict[str, Any]:
        """Transport-agnostic reset/purge hook for command and future web API handlers."""
        session = normalize_session(session or DEFAULT_SESSION)
        repo_name = self._session_repo_name(channel_id, session)
        statuses = await self.coordinator.snapshot(channel_id)
        queued_ids = [s.job_id for s in statuses if s.status == "queued" and (s.session or DEFAULT_SESSION) == session]
        for job_id in queued_ids:
            await self.coordinator.cancel(channel_id, job_id)

        running_job = any(s.status == "running" and (s.session or DEFAULT_SESSION) == session for s in statuses)
        proc = await self.get_active(channel_id, session)
        killed = False
        blocked_running = False
        if proc is not None:
            await proc.kill()
            killed = True
        elif running_job:
            blocked_running = True

        removed = False
        purged_artifacts = 0
        if not blocked_running:
            removed = await self.coordinator.reset_session(channel_id, session)
            self.clear_awaiting_input(channel_id, session)
            if purge:
                # Allow exit callbacks to flush any final log events before purge deletion.
                await asyncio.sleep(0)
                purged_artifacts = self._purge_session_artifacts(channel_id, session, repo_name)
                await asyncio.sleep(0)
                purged_artifacts += self._purge_session_artifacts(channel_id, session, repo_name)
        return {
            "channel_id": channel_id,
            "session": session,
            "repo_name": repo_name,
            "removed": removed,
            "killed": killed,
            "cancelled_jobs": len(queued_ids),
            "blocked_running": blocked_running,
            "purged_artifacts": purged_artifacts,
        }

    async def api_reset_session(self, channel_id: str, session: str, purge: bool = False) -> dict[str, Any]:
        """Future web API hook for session reset/purge operations."""
        return await self.control_reset_session(channel_id, session, purge=purge)

    def _session_repo_name(self, channel_id: str, session: str) -> str:
        state = self.state.load()
        ch = state.channels.get(channel_id)
        if not ch:
            return ""
        sess = ch.sessions.get(session)
        if not sess:
            return ""
        return str(getattr(sess, "repo_name", "") or "")

    def _purge_session_artifacts(self, channel_id: str, session: str, repo_name: str) -> int:
        removed = 0

        for path in self._session_log.session_paths(channel_id, session, repo_name=repo_name):
            try:
                if path.exists():
                    path.unlink()
                    removed += 1
            except Exception as exc:
                self.logger.warning("session.purge.remove_failed", extra={"path": str(path), "error": str(exc)})

        archive_dirs = {
            self._session_archive_dir(channel_id, session, repo_name),
            self._session_archive_dir(channel_id, session, ""),
            os.path.join(
                self.cfg.state.log_dir or tempfile.gettempdir(),
                "session_archives",
                safe_segment(channel_id or "channel", "channel"),
                safe_segment(session or DEFAULT_SESSION, "default"),
            ),
        }
        for archive_dir in archive_dirs:
            path_obj = Path(archive_dir)
            if not path_obj.is_dir():
                continue
            for item in path_obj.glob("*.txt"):
                try:
                    item.unlink()
                    removed += 1
                except Exception as exc:
                    self.logger.warning("session.purge.remove_failed", extra={"path": str(item), "error": str(exc)})
        if not repo_name:
            wildcard_root = Path(self.cfg.state.log_dir or tempfile.gettempdir()) / "session_archives" / safe_segment(channel_id or "channel", "channel")
            if wildcard_root.is_dir():
                for dir_path in wildcard_root.glob(f"repo-*__session-{safe_segment(session or DEFAULT_SESSION, 'default')}"):
                    for item in dir_path.glob("*.txt"):
                        try:
                            item.unlink()
                            removed += 1
                        except Exception as exc:
                            self.logger.warning("session.purge.remove_failed", extra={"path": str(item), "error": str(exc)})

        channel_dir = Path(self.cfg.state.log_dir or "") / safe_segment(channel_id, "channel")
        if channel_dir.is_dir():
            legacy_dir = channel_dir / safe_segment(session, "default")
            prefixed_dir = channel_dir / session_artifact_label(repo_name, session)
            candidates = {legacy_dir, prefixed_dir}
            if not repo_name:
                candidates.update(channel_dir.glob(f"repo-*__session-{safe_segment(session, 'default')}"))
            for candidate in candidates:
                if not candidate.is_dir():
                    continue
                for file_path in candidate.rglob("*"):
                    if not file_path.is_file():
                        continue
                    try:
                        file_path.unlink()
                        removed += 1
                    except Exception as exc:
                        self.logger.warning(
                            "session.purge.remove_failed",
                            extra={"path": str(file_path), "error": str(exc)},
                        )
        return removed

    async def handle_stats(self, sink: ResponseSink, session: str) -> None:
        """Show token usage stats for a session."""
        stats = self._usage.get(sink.channel_id, {}).get(session)
        if not stats:
            await self.reply_forbidden(sink, "No usage stats yet.")
            return
        await self.reply(
            sink,
            f"session {session}: input {stats.input_tokens}, output {stats.output_tokens}, total {stats.total_tokens}",
        )

    async def handle_peek(self, sink: ResponseSink, session: str) -> None:
        """Show running status and last output time."""
        active = await self.get_active(sink.channel_id, session)
        last = self.get_activity(sink.channel_id, session)
        if active is None:
            await self.reply(sink, f"Codex is idle. Last output at {last or 'n/a'}.")
            return
        await self.reply(sink, f"Codex is running for session '{session}'.")

    async def send_status(self, event: MessageEvent, sink: ResponseSink, repo_name: str, repo_path: str) -> None:
        """Send status summary for the channel and sessions."""
        state = self.state.load()
        queue_statuses = await self.coordinator.snapshot(sink.channel_id)
        waiting = self._prune_awaiting_input(sink.channel_id)
        related: list[str] = []
        if queue_statuses:
            related.append("!ps")
        if waiting:
            related.append("!w")
        ch = state.channels.get(sink.channel_id)
        if ch and ch.sessions:
            lines = [
                f"Repo: {repo_name}",
                f"Path: {repo_path}",
                self._format_unlock_status_line(event),
                f"Sessions ({len(ch.sessions)}/{MAX_SESSIONS_PER_CHANNEL}):",
            ]
            for name, sess in ch.sessions.items():
                active = await self.get_active(sink.channel_id, name) is not None
                lines.append(
                    format_session_line(
                        name,
                        sess,
                        active,
                        self.cfg.codex.model,
                        self.cfg.codex.model_reasoning_effort,
                        bool(self._runtime_option_value(sink.channel_id, "show_reasoning_details")),
                    )
                )
            current = self.current_session_for_user("", sink.channel_id)
            if current:
                current_model = self.session_model(sink.channel_id, current)
                current_reasoning = self.session_reasoning_effort(sink.channel_id, current)
                lines.append(
                    format_current_selection_line(
                        current,
                        current_model,
                        current_reasoning,
                        bool(self._runtime_option_value(sink.channel_id, "show_reasoning_details")),
                    )
                )
            await self.reply(sink, self._with_related("\n".join(lines), *related))
            return
        await self.reply(
            sink,
            self._with_related(
                f"Repo: {repo_name}\nPath: {repo_path}\n{self._format_unlock_status_line(event)}\nNo session attached.",
                "!c start",
                *related,
            ),
        )

    def _with_related(self, message: str, *commands: str) -> str:
        unique: list[str] = []
        for cmd in commands:
            token = (cmd or "").strip()
            if token and token not in unique:
                unique.append(token)
        if not unique:
            return message
        return f"{message}\nRelated: {', '.join(unique)}"

    async def send_help(self, event: MessageEvent, sink: ResponseSink, query: str = "") -> None:
        """Send help text for supported commands."""
        prefix = self._transport_prefix(event)
        token = (query or "").strip().lower()
        if not token:
            await self.reply(sink, command_registry.render_help(self._command_specs, prefix=prefix))
            return
        spec = self._command_registry.get(token)
        if not spec:
            await self.reply_forbidden(sink, help_renderer.help_not_found(token, self._command_registry, prefix))
            return
        await self.reply(sink, help_renderer.render_help_command(spec, prefix=prefix))

    async def startup_summary(self) -> str:
        """Return a concise summary of the current bridge state."""
        state = self.state.load()
        channel_count = len(state.channels)
        session_count = sum(len(ch.sessions) for ch in state.channels.values())
        repos = {
            sess.repo_name
            for ch in state.channels.values()
            for sess in ch.sessions.values()
            if sess.repo_name
        }
        snapshot = await self.coordinator.snapshot_all()
        running = sum(
            1
            for statuses in snapshot.values()
            for status in statuses
            if status.status == "running"
        )
        queued = sum(
            1
            for statuses in snapshot.values()
            for status in statuses
            if status.status == "queued"
        )
        default_model = self.cfg.codex.model or "<default>"
        default_reasoning = self.cfg.codex.model_reasoning_effort or "<default>"
        code_root = self.cfg.codex.code_root or "<unset>"
        state_dir = self.cfg.state.data_dir or "<unset>"
        lines = [
            f"Bot ready (commit {self._commit})",
            f"Default model: {default_model} (reasoning {default_reasoning})",
            f"Code root: {code_root}",
            f"State dir: {state_dir}",
            f"Tracking {len(repos)} repos across {channel_count} channels and {session_count} sessions",
            f"Queue: {running} running, {queued} queued",
        ]
        summary = "\n".join(lines)
        self.logger.info(
            "startup.summary",
            extra={
                "channels": channel_count,
                "sessions": session_count,
                "repos": len(repos),
                "running_jobs": running,
                "queued_jobs": queued,
            },
        )
        return summary

    async def shutdown_summary(self) -> str:
        """Return a concise shutdown summary for the bridge."""
        state = self.state.load()
        channel_count = len(state.channels)
        session_count = sum(len(ch.sessions) for ch in state.channels.values())
        snapshot = await self.coordinator.snapshot_all()
        running = sum(
            1
            for statuses in snapshot.values()
            for status in statuses
            if status.status == "running"
        )
        queued = sum(
            1
            for statuses in snapshot.values()
            for status in statuses
            if status.status == "queued"
        )
        lines = [
            f"Shutdown summary (commit {self._commit})",
            f"Tracking {channel_count} channels and {session_count} sessions",
            f"Queue at shutdown: {running} running, {queued} queued",
        ]
        summary = "\n".join(lines)
        self.logger.info(
            "shutdown.summary",
            extra={
                "channels": channel_count,
                "sessions": session_count,
                "running_jobs": running,
                "queued_jobs": queued,
            },
        )
        return summary

    def config_text(self) -> str:
        """Render a concise config summary."""
        return render_config_text(self.cfg)

    async def run_codex(
        self,
        event: MessageEvent,
        sink: ResponseSink,
        repo_name: str,
        repo_path: str,
        session: str,
        model: str,
        reasoning_effort: str,
        args: list[str],
        on_output=None,
        relay_output: bool = True,
    ) -> None:
        """Run Codex with streaming callbacks and audit logging."""
        channel_id = event.channel_id
        if await self._budget_hard_blocked(event, sink):
            return
        started_at = time.monotonic()
        last_output = ""
        output_events = 0
        usage_before = self.get_usage(channel_id, session)
        before_total = usage_before.total_tokens if usage_before else 0

        async def _capture_output(text: str) -> None:
            nonlocal last_output, output_events
            clean = strip_control_codes((text or "").strip())
            if clean:
                output_events += 1
                last_output = clean
            if on_output:
                await on_output(text)

        original_args = list(args)
        meta = {
            "repo_name": repo_name,
            "repo_path": repo_path,
            "args": original_args,
            "model": model,
            "reasoning_effort": reasoning_effort,
            "session": session or DEFAULT_SESSION,
            "timestamp": utc_now_iso(),
            "channel": channel_id,
        }
        self._session_log.append(
            channel_id,
            session or DEFAULT_SESSION,
            "run.start",
            {
                "repo_name": repo_name,
                "repo_path": repo_path,
                "model": model,
                "reasoning_effort": reasoning_effort,
                "args": original_args,
            },
            repo_name=repo_name,
        )
        entry = self._audit_helper.start(channel_id, session or DEFAULT_SESSION, "pending", meta)
        stderr_tail: list[str] = []

        async def _on_stderr(line: str) -> None:
            self._audit_helper.append_stderr(entry, line)
            self._session_log.append(
                channel_id,
                session or DEFAULT_SESSION,
                "codex.stderr",
                {"line": line},
                repo_name=repo_name,
            )
            text = strip_control_codes((line or "").strip())
            if not text:
                return
            stderr_tail.append(text)
            if len(stderr_tail) > 5:
                del stderr_tail[: len(stderr_tail) - 5]

        async with self.typing_context(sink):
            args_to_run = list(original_args)
            stderr_tail.clear()
            try:
                proc = await self.runner.run(
                    Options(
                        repo_path=repo_path,
                        args=args_to_run,
                        env=self.cfg.codex.env,
                        on_jsonl=lambda line: self.on_jsonl(
                            sink, channel_id, session, repo_name, entry, line, relay_output
                        ),
                        on_thread=lambda tid: self.on_thread(
                            channel_id, session, repo_name, repo_path, model, reasoning_effort, entry, tid
                        ),
                        on_output=_capture_output,
                        on_stderr=_on_stderr,
                        on_exit=lambda err, rc: self.on_exit(channel_id, session, repo_name, err, rc),
                    )
                )
            except Exception as exc:
                self._append_codex_error_log(
                    channel_id=channel_id,
                    session=session,
                    repo_name=repo_name,
                    repo_path=repo_path,
                    args=args_to_run,
                    return_code=None,
                    stderr_lines=stderr_tail,
                    note=f"failed to start: {exc}",
                )
                self._session_log.append(
                    channel_id,
                    session or DEFAULT_SESSION,
                    "run.start_failed",
                    {"error": str(exc)},
                    repo_name=repo_name,
                )
                self._audit_helper.close(entry)
                await self.reply_forbidden(sink, f"Codex failed to start: {exc}")
                return

            await self.set_active(channel_id, session, proc)
            heartbeat_task: asyncio.Task | None = None
            if relay_output:
                heartbeat_task = asyncio.create_task(self._run_heartbeat(sink, session, started_at))
            try:
                rc = await proc.wait()
            finally:
                if heartbeat_task:
                    heartbeat_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await heartbeat_task
                await self.clear_active(channel_id, session)

            if rc == 0:
                usage_after = self.get_usage(channel_id, session)
                after_total = usage_after.total_tokens if usage_after else 0
                delta_total = max(0, after_total - before_total)
                if delta_total:
                    self._budget_record_usage(event, channel_id, delta_total)
                if relay_output:
                    await self._send_run_completion_summary(
                        sink,
                        channel_id,
                        session,
                        started_at,
                        output_events,
                        last_output,
                    )
                self._session_log.append(
                    channel_id,
                    session or DEFAULT_SESSION,
                    "run.complete",
                    {"code": 0, "output_events": output_events},
                    repo_name=repo_name,
                )
            else:
                self.logger.warning("codex.exit", extra={"channel_id": channel_id, "repo": repo_name, "session": session, "code": rc})
                self._append_codex_error_log(
                    channel_id=channel_id,
                    session=session,
                    repo_name=repo_name,
                    repo_path=repo_path,
                    args=args_to_run,
                    return_code=rc,
                    stderr_lines=stderr_tail,
                    note="non-zero exit",
                )
                detail = f"Codex exited with code {rc}."
                if stderr_tail:
                    detail += f" Last stderr: {stderr_tail[-1]}"
                detail += " Use `!c logs` for details."
                await self.reply_forbidden(sink, detail)
                self._session_log.append(
                    channel_id,
                    session or DEFAULT_SESSION,
                    "run.failed",
                    {"code": rc, "stderr_tail": list(stderr_tail[-5:])},
                    repo_name=repo_name,
                )
            self._audit_helper.close(entry)
        await self._budget_soft_notify_if_needed(event, sink)

    def _budget_user_key(self, event: MessageEvent) -> str:
        return f"{event.platform}:{event.author_id}"

    def _budget_thresholds(self, event: MessageEvent) -> tuple[tuple[int, int], tuple[int, int]]:
        ch = self._budget_thresholds_channel.get(event.channel_id, (0, 0))
        user = self._budget_thresholds_user.get(self._budget_user_key(event), (0, 0))
        return ch, user

    async def _budget_hard_blocked(self, event: MessageEvent, sink: ResponseSink) -> bool:
        ch_thr, user_thr = self._budget_thresholds(event)
        ch_used = self._budget_usage_channel.get(event.channel_id, 0)
        user_used = self._budget_usage_user.get(self._budget_user_key(event), 0)
        ch_hard = ch_thr[1]
        user_hard = user_thr[1]
        reasons: list[str] = []
        if ch_hard > 0 and ch_used >= ch_hard:
            reasons.append(f"channel hard budget reached ({ch_used}/{ch_hard})")
        if user_hard > 0 and user_used >= user_hard:
            reasons.append(f"user hard budget reached ({user_used}/{user_hard})")
        if not reasons:
            return False
        await self.reply_forbidden(sink, "Budget limit reached: " + "; ".join(reasons) + ". Use `!c budget status`.")
        return True

    def _budget_record_usage(self, event: MessageEvent, channel_id: str, total_tokens: int) -> None:
        self._budget_usage_channel[channel_id] = self._budget_usage_channel.get(channel_id, 0) + total_tokens
        user_key = self._budget_user_key(event)
        self._budget_usage_user[user_key] = self._budget_usage_user.get(user_key, 0) + total_tokens

    async def _budget_soft_notify_if_needed(self, event: MessageEvent, sink: ResponseSink) -> None:
        ch_thr, user_thr = self._budget_thresholds(event)
        ch_soft = ch_thr[0]
        user_soft = user_thr[0]
        ch_used = self._budget_usage_channel.get(event.channel_id, 0)
        user_used = self._budget_usage_user.get(self._budget_user_key(event), 0)
        notices: list[str] = []
        if ch_soft > 0 and ch_used >= ch_soft:
            notices.append(f"channel soft budget reached ({ch_used}/{ch_soft})")
        if user_soft > 0 and user_used >= user_soft:
            notices.append(f"user soft budget reached ({user_used}/{user_soft})")
        if notices:
            await self.reply(sink, "Budget notice: " + "; ".join(notices) + ".")

    def _budget_status_text(self, event: MessageEvent) -> str:
        ch_thr, user_thr = self._budget_thresholds(event)
        ch_used = self._budget_usage_channel.get(event.channel_id, 0)
        user_used = self._budget_usage_user.get(self._budget_user_key(event), 0)
        return (
            "Budgets:\n"
            f"- Channel usage: {ch_used} tokens | soft={ch_thr[0]} hard={ch_thr[1]}\n"
            f"- User usage: {user_used} tokens | soft={user_thr[0]} hard={user_thr[1]}"
        )

    async def _run_heartbeat(self, sink: ResponseSink, session: str, started_at: float) -> None:
        """Emit periodic run heartbeat messages while a job is active."""
        while True:
            await asyncio.sleep(self._runtime_option_value(sink.channel_id, "run_heartbeat_seconds"))
            elapsed = int(max(1.0, time.monotonic() - started_at))
            await self.reply(sink, f"Still running in session '{session}' ({self._format_duration(elapsed)} elapsed).")

    async def _send_run_completion_summary(
        self,
        sink: ResponseSink,
        channel_id: str,
        session: str,
        started_at: float,
        output_events: int,
        last_output: str,
    ) -> None:
        """Send concise completion details for a successful run."""
        elapsed = int(max(1.0, time.monotonic() - started_at))
        if elapsed < self._runtime_option_value(channel_id, "run_completion_min_seconds"):
            return
        parts = [f"Run complete for session '{session}' in {self._format_duration(elapsed)}."]
        usage = self.get_usage(channel_id, session)
        if usage and usage.total_tokens:
            parts.append(
                f"Tokens in/out/total: {usage.input_tokens}/{usage.output_tokens}/{usage.total_tokens}."
            )
        if output_events:
            parts.append(f"Output events: {output_events}.")
        if last_output:
            clipped = last_output[:_RUN_KEY_RESULT_MAX]
            if len(last_output) > _RUN_KEY_RESULT_MAX:
                clipped += "..."
            parts.append(f"Key result: {clipped}")
        await self.reply(sink, " ".join(parts))

    async def on_jsonl(
        self,
        sink: ResponseSink,
        channel_id: str,
        session: str,
        repo_name: str,
        entry: Optional[Entry],
        line: str,
        relay_output: bool,
    ) -> None:
        """Handle a JSONL line from Codex and relay output."""
        self._session_log.append(
            channel_id,
            session or DEFAULT_SESSION,
            "codex.jsonl",
            {"line": line},
            repo_name=repo_name,
        )
        self._audit_helper.append_codex(entry, line)
        evt = parse_event(line)
        if not evt:
            text = strip_control_codes(line).strip()
            if text and relay_output:
                for chunk in chunk_text(text, self.cfg.discord.max_discord_message_chars):
                    self._audit_helper.append_output(entry, chunk)
                    self._session_log.append(
                        channel_id,
                        session or DEFAULT_SESSION,
                        "discord.output",
                        {"chunk": chunk},
                        repo_name=repo_name,
                    )
                    await self.reply(sink, chunk)
            return
        self.update_usage(channel_id, session, evt)
        self.update_activity(channel_id, session)
        for msg in display_texts(evt):
            text = strip_control_codes(msg)
            if needs_user_input(text):
                self._mark_awaiting_input(channel_id, session)
                text = f"Codex asks: {text}"
            if relay_output:
                for chunk in chunk_text(text, self.cfg.discord.max_discord_message_chars):
                    self._audit_helper.append_output(entry, chunk)
                    self._session_log.append(
                        channel_id,
                        session or DEFAULT_SESSION,
                        "discord.output",
                        {"chunk": chunk},
                        repo_name=repo_name,
                    )
                    await self.reply(sink, chunk)

    async def on_thread(
        self,
        channel_id: str,
        session: str,
        repo_name: str,
        repo_path: str,
        model: str,
        reasoning_effort: str,
        entry: Optional[Entry],
        thread_id: str,
    ) -> None:
        """Handle thread id updates from Codex."""
        if entry:
            entry.thread_id = thread_id
            entry.session = session or DEFAULT_SESSION
        self._session_log.append(
            channel_id,
            session or DEFAULT_SESSION,
            "codex.thread",
            {"thread_id": thread_id},
            repo_name=repo_name,
        )
        self.update_state(channel_id, session, repo_name, repo_path, thread_id, model, reasoning_effort)

    async def on_exit(self, channel_id: str, session: str, repo_name: str, err: Optional[BaseException], rc: int) -> None:
        """Handle Codex process exit events."""
        await self.clear_active(channel_id, session)
        self.clear_awaiting_input(channel_id, session)
        if err:
            self.logger.error("codex.exit", extra={"channel_id": channel_id, "repo": repo_name, "session": session, "error": str(err)})
            self._session_log.append(
                channel_id,
                session or DEFAULT_SESSION,
                "codex.exit",
                {"error": str(err)},
                repo_name=repo_name,
            )
            return
        self.logger.info("codex.exit", extra={"channel_id": channel_id, "repo": repo_name, "session": session, "code": rc})
        self._session_log.append(
            channel_id,
            session or DEFAULT_SESSION,
            "codex.exit",
            {"code": rc},
            repo_name=repo_name,
        )

    async def reply(self, sink: ResponseSink, content: str) -> None:
        """Send a reply to a channel, chunking as needed."""
        await send_reply(sink, content, self.cfg.discord.max_discord_message_chars)

    async def reply_forbidden(self, sink: ResponseSink, detail: str) -> None:
        """Send a standardized forbidden/invalid response."""
        await send_forbidden(sink, detail, self.cfg.discord.max_discord_message_chars)

    def _mark_awaiting_input(self, channel_id: str, session: str) -> None:
        session = session or DEFAULT_SESSION
        expires_at = time.time() + _AWAITING_INPUT_TTL_SECONDS
        self._awaiting_input.setdefault(channel_id, {})[session] = expires_at

    def clear_awaiting_input(self, channel_id: str, session: str) -> None:
        session = session or DEFAULT_SESSION
        sessions = self._awaiting_input.get(channel_id)
        if not sessions:
            return
        sessions.pop(session, None)
        if not sessions:
            self._awaiting_input.pop(channel_id, None)

    def _prune_awaiting_input(self, channel_id: str) -> dict[str, float]:
        sessions = self._awaiting_input.get(channel_id, {})
        if not sessions:
            return {}
        now = time.time()
        stale = [name for name, expires_at in sessions.items() if expires_at <= now]
        for name in stale:
            sessions.pop(name, None)
        if not sessions:
            self._awaiting_input.pop(channel_id, None)
            return {}
        return dict(sessions)

    async def pending_input_session(self, event: MessageEvent) -> tuple[str, bool]:
        """Resolve a session awaiting user input; returns (session, ambiguous)."""
        pending = self._prune_awaiting_input(event.channel_id)
        if not pending:
            return "", False
        preferred = self.current_session_for_event(event) or DEFAULT_SESSION
        if preferred in pending and await self.get_active(event.channel_id, preferred):
            return preferred, False
        candidates: list[str] = []
        for session_name in sorted(pending.keys()):
            if await self.get_active(event.channel_id, session_name):
                candidates.append(session_name)
        if len(candidates) == 1:
            return candidates[0], False
        if len(candidates) > 1:
            return "", True
        return "", False

    def _dm_admin_allowed(self, user_id: str) -> bool:
        if self.cfg.discord.dm_admin_user_ids:
            return user_id in self.cfg.discord.dm_admin_user_ids
        return user_id in self.cfg.discord.allowed_user_ids

    def _totp_enabled(self, event: MessageEvent) -> bool:
        return self.cfg.discord.totp_enabled

    def _canonical_command(self, cmd: str) -> str:
        token = (cmd or "").strip().lower()
        if not token:
            return token
        spec = self._command_registry.get(token)
        if not spec:
            return token
        return spec.name

    def _command_auth_mode(self, cmd: str) -> str:
        token = self._canonical_command(cmd)
        spec = self._command_registry.get(token)
        if not spec:
            return ""
        return getattr(spec, "auth", "")

    def _totp_required_for_command(self, event: MessageEvent, cmd: str, rest: str) -> bool:
        token = self._canonical_command(cmd)
        auth_mode = self._command_auth_mode(token)
        if token == "options":
            if self._options_show_requested(rest):
                return False
            return not self._totp_is_unlocked(event)
        if token == "lock":
            if self._lock_status_requested(rest):
                return False
            if self._lock_extend_requested(rest):
                return self.cfg.discord.totp_enforce_high_risk
            return False
        if token == "unlock" and self._unlock_status_requested(rest):
            return False
        if token == "git":
            if not self.cfg.discord.totp_enforce_git:
                return False
            if self._git_command_is_high_risk(rest):
                return self.cfg.discord.totp_enforce_high_risk
            return not self._totp_is_unlocked(event)
        if token == "gh":
            if not self.cfg.discord.totp_enforce_gh:
                return False
            return not self._totp_is_unlocked(event, _UNLOCK_SCOPE_GH)
        if auth_mode == command_registry.AUTH_OPEN:
            return False
        if auth_mode == command_registry.AUTH_UNLOCK:
            return not self._totp_is_unlocked(event)
        if auth_mode == command_registry.AUTH_UNLOCK_GH:
            if not self.cfg.discord.totp_enforce_gh:
                return False
            return not self._totp_is_unlocked(event, _UNLOCK_SCOPE_GH)
        if auth_mode == command_registry.AUTH_TOTP:
            return self.cfg.discord.totp_enforce_high_risk
        if auth_mode == command_registry.AUTH_MIXED:
            return not self._totp_is_unlocked(event)
        if self._totp_command_is_high_risk(token, rest):
            return self.cfg.discord.totp_enforce_high_risk
        if token in _READ_ONLY_COMMANDS:
            return False
        if self._totp_is_unlocked(event):
            return False
        return True

    def _totp_command_is_high_risk(self, cmd: str, rest: str) -> bool:
        if cmd in {"create", "clone", "copy", "deleterepo", "delete", "renamerepo", "rename"}:
            return True
        if cmd == "unlock" and not self._unlock_status_requested(rest):
            return True
        return False

    def _git_command_is_high_risk(self, rest: str) -> bool:
        raw = (rest or "").strip()
        if not raw:
            return False
        try:
            fields = shlex.split(raw)
        except ValueError:
            fields = raw.split()
        if not fields:
            return False
        sub = fields[0].lower()
        args = [a.lower() for a in fields[1:]]
        if sub != "remote" or not args:
            return False
        return args[0] in {"set-url", "add", "remove", "rename", "set-head"}

    def _unlock_status_requested(self, rest: str) -> bool:
        parts = (rest or "").strip().lower().split()
        if not parts:
            return False
        if parts[0] in _UNLOCK_STATUS_TOKENS:
            return True
        return len(parts) >= 2 and parts[0] in {"all", _UNLOCK_SCOPE_DEFAULT, _UNLOCK_SCOPE_GH} and parts[1] in _UNLOCK_STATUS_TOKENS

    def _options_show_requested(self, rest: str) -> bool:
        parts = (rest or "").strip().lower().split()
        if not parts:
            return True
        return parts[0] in {"show", "status", "list"}

    def _options_usage_hint(self, is_dm: bool) -> str:
        if is_dm:
            return (
                "Usage: !c options [show] | !c options set <key> <value> [local|global]\n"
                f"Allowed keys: {', '.join(_RUNTIME_OPTION_KEYS)}\n"
                "Examples:\n"
                "- !c options set run_heartbeat_seconds 120 local\n"
                "- !c options set show_reasoning_details false global"
            )
        return (
            "Usage: !c options [show] | !c options set <key> <value>\n"
            f"Allowed keys: {', '.join(_RUNTIME_OPTION_KEYS)}\n"
            "Channel commands always use local scope.\n"
            "Example: !c options set run_completion_min_seconds 300"
        )

    def _sanitize_runtime_option(self, key: str, value: Any) -> Any:
        if key in {"run_heartbeat_seconds", "run_completion_min_seconds"}:
            parsed = int(value)
            if parsed < 1 or parsed > 86400:
                raise ValueError(f"{key} must be between 1 and 86400.")
            return parsed
        if key == "show_reasoning_details":
            return parse_bool(value)
        raise ValueError(f"Unknown option key: {key}")

    def _load_runtime_options_from_state(self) -> None:
        try:
            fs = self.state.load()
        except Exception:
            return
        global_raw = getattr(fs, "runtime_options_global", {}) or {}
        channel_raw = getattr(fs, "runtime_options_channels", {}) or {}
        for key, value in global_raw.items():
            if key not in _RUNTIME_OPTION_KEYS:
                continue
            try:
                self._runtime_options_global[key] = self._sanitize_runtime_option(key, value)
            except Exception:
                continue
        for channel_id, options in channel_raw.items():
            if not isinstance(options, dict):
                continue
            scoped: Dict[str, Any] = {}
            for key, value in options.items():
                if key not in _RUNTIME_OPTION_KEYS:
                    continue
                try:
                    scoped[key] = self._sanitize_runtime_option(key, value)
                except Exception:
                    continue
            if scoped:
                self._runtime_options_channels[str(channel_id)] = scoped

    def _persist_runtime_options(self) -> None:
        global_copy = dict(self._runtime_options_global)
        channel_copy = {ch: dict(values) for ch, values in self._runtime_options_channels.items() if values}

        def mutator(fs):
            fs.runtime_options_global = global_copy
            fs.runtime_options_channels = channel_copy

        self.state.update(mutator)

    def _set_runtime_option(self, scope: str, channel_id: str, key: str, value: Any) -> None:
        normalized = self._sanitize_runtime_option(key, value)
        if scope == "global":
            self._runtime_options_global[key] = normalized
        else:
            channel_key = str(channel_id or "")
            scoped = self._runtime_options_channels.get(channel_key)
            if scoped is None:
                scoped = {}
                self._runtime_options_channels[channel_key] = scoped
            scoped[key] = normalized
        self._persist_runtime_options()

    def _effective_runtime_options(self, channel_id: str) -> Dict[str, Any]:
        out = dict(self._runtime_defaults)
        out.update(self._runtime_options_global)
        out.update(self._runtime_options_channels.get(str(channel_id or ""), {}))
        return out

    def _runtime_option_value(self, channel_id: str, key: str) -> Any:
        effective = self._effective_runtime_options(channel_id)
        return effective.get(key, self._runtime_defaults.get(key))

    def _runtime_options_text(self, channel_id: str, is_dm: bool) -> str:
        effective = self._effective_runtime_options(channel_id)
        lines = [
            "Runtime options (persisted):",
            f"- local.run_heartbeat_seconds: {effective['run_heartbeat_seconds']}",
            f"- local.run_completion_min_seconds: {effective['run_completion_min_seconds']}",
            f"- local.show_reasoning_details: {effective['show_reasoning_details']}",
        ]
        if is_dm:
            lines.extend(
                [
                    f"- global.run_heartbeat_seconds: {self._runtime_options_global.get('run_heartbeat_seconds', '<unset>')}",
                    f"- global.run_completion_min_seconds: {self._runtime_options_global.get('run_completion_min_seconds', '<unset>')}",
                    f"- global.show_reasoning_details: {self._runtime_options_global.get('show_reasoning_details', '<unset>')}",
                    "DM set usage: !c options set <key> <value> [local|global]",
                ]
            )
        else:
            lines.append("Channel set usage: !c options set <key> <value> (always local scope)")
        return "\n".join(lines)

    def _parse_unlock_action(self, rest: str) -> tuple[str, str, str]:
        raw = (rest or "").strip()
        if not raw:
            return "set", _UNLOCK_SCOPE_DEFAULT, ""
        parts = raw.split()
        first = parts[0].lower()
        if first in _UNLOCK_STATUS_TOKENS:
            if len(parts) != 1:
                raise ValueError(
                    "Usage: !c unlock [gh|all] <totp> [ttl], !c unlock [gh|all] status, or !c unlock extend [gh|all] <ttl>"
                )
            return "status", "all", "status"
        if first == "extend":
            if len(parts) == 2:
                return "extend", _UNLOCK_SCOPE_DEFAULT, parts[1]
            if len(parts) == 3 and parts[1].lower() in {"all", _UNLOCK_SCOPE_DEFAULT, _UNLOCK_SCOPE_GH}:
                return "extend", parts[1].lower(), parts[2]
            raise ValueError(
                "Usage: !c unlock [gh|all] <totp> [ttl], !c unlock [gh|all] status, or !c unlock extend [gh|all] <ttl>"
            )
        scope = _UNLOCK_SCOPE_DEFAULT
        idx = 0
        if first in {"all", _UNLOCK_SCOPE_DEFAULT, _UNLOCK_SCOPE_GH}:
            scope = first
            idx = 1
        tail = parts[idx:]
        if not tail:
            return "set", scope, ""
        marker = tail[0].lower()
        if marker in _UNLOCK_STATUS_TOKENS:
            if len(tail) != 1:
                raise ValueError(
                    "Usage: !c unlock [gh|all] <totp> [ttl], !c unlock [gh|all] status, or !c unlock extend [gh|all] <ttl>"
                )
            return "status", scope, "status"
        if len(tail) != 1:
            raise ValueError(
                "Usage: !c unlock [gh|all] <totp> [ttl], !c unlock [gh|all] status, or !c unlock extend [gh|all] <ttl>"
            )
        return "set", scope, tail[0]

    def _lock_status_requested(self, rest: str) -> bool:
        parts = (rest or "").strip().lower().split()
        if not parts:
            return False
        if parts[0] in _UNLOCK_STATUS_TOKENS:
            return True
        return len(parts) >= 2 and parts[0] == "status" and parts[1] in {"all", _UNLOCK_SCOPE_DEFAULT, _UNLOCK_SCOPE_GH}

    def _lock_extend_requested(self, rest: str) -> bool:
        parts = (rest or "").strip().lower().split()
        return bool(parts) and parts[0] == "extend"

    def _parse_lock_action(self, rest: str) -> tuple[str, str, Optional[int]]:
        raw = (rest or "").strip()
        if not raw:
            return "clear", "all", None
        parts = raw.split()
        first = parts[0].lower()
        if first in {"all", _UNLOCK_SCOPE_DEFAULT, _UNLOCK_SCOPE_GH} and len(parts) == 1:
            return "clear", first, None
        if first == "status" or first in _UNLOCK_STATUS_TOKENS:
            if first in _UNLOCK_STATUS_TOKENS and len(parts) == 1:
                return "status", "all", None
            if first == "status":
                scope = "all"
                if len(parts) >= 2:
                    scope = parts[1].lower()
                if scope not in {"all", _UNLOCK_SCOPE_DEFAULT, _UNLOCK_SCOPE_GH} or len(parts) > 2:
                    raise ValueError("Usage: !c lock [gh|all] | !c lock status [gh|all] | !c lock extend [gh|all] <ttl>")
                return "status", scope, None
        if first == "extend":
            if len(parts) == 2:
                scope = _UNLOCK_SCOPE_DEFAULT
                ttl_text = parts[1]
            elif len(parts) == 3:
                scope = parts[1].lower()
                ttl_text = parts[2]
                if scope not in {"all", _UNLOCK_SCOPE_DEFAULT, _UNLOCK_SCOPE_GH}:
                    raise ValueError("Usage: !c lock [gh|all] | !c lock status [gh|all] | !c lock extend [gh|all] <ttl>")
            else:
                raise ValueError("Usage: !c lock [gh|all] | !c lock status [gh|all] | !c lock extend [gh|all] <ttl>")
            ttl_seconds = self._parse_unlock_ttl_seconds(ttl_text)
            return "extend", scope, ttl_seconds
        raise ValueError("Usage: !c lock [gh|all] | !c lock status [gh|all] | !c lock extend [gh|all] <ttl>")

    async def _reply_unlock_status(self, event: MessageEvent, sink: ResponseSink, scope: str) -> None:
        scopes = [_UNLOCK_SCOPE_DEFAULT, _UNLOCK_SCOPE_GH] if scope == "all" else [scope]
        labels = {_UNLOCK_SCOPE_DEFAULT: "default", _UNLOCK_SCOPE_GH: "gh"}
        lines: list[str] = []
        for realm in scopes:
            remaining = self._totp_unlock_remaining(event, realm)
            if remaining <= 0:
                lines.append(f"TOTP {labels.get(realm, realm)} unlock: inactive.")
                continue
            lines.append(f"TOTP {labels.get(realm, realm)} unlock: active for {self._format_duration(remaining)}.")
        await self.reply(sink, "\n".join(lines))

    async def _extend_unlock_window(self, event: MessageEvent, sink: ResponseSink, scope: str, ttl_seconds: int) -> None:
        scopes = [_UNLOCK_SCOPE_DEFAULT, _UNLOCK_SCOPE_GH] if scope == "all" else [scope]
        labels = {_UNLOCK_SCOPE_DEFAULT: "default", _UNLOCK_SCOPE_GH: "gh"}
        now = time.time()
        missing = [realm for realm in scopes if self._totp_unlock_remaining(event, realm) <= 0]
        if missing:
            rendered = ", ".join(labels.get(r, r) for r in missing)
            await self.reply_forbidden(
                sink,
                f"No active unlock window to extend for: {rendered}. Use `!c unlock` first.",
            )
            return
        lines: list[str] = []
        for realm in scopes:
            key = self._totp_unlock_scope_key(event, realm)
            current_until = self._totp_unlock_until.get(key, 0.0)
            base = current_until if current_until > now else now
            new_until = base + max(1, ttl_seconds)
            self._totp_unlock_until[key] = new_until
            old_remaining = max(0, int(current_until - now))
            new_remaining = max(0, int(new_until - now))
            lines.append(
                f"TOTP {labels.get(realm, realm)} unlock extended by {self._format_duration(ttl_seconds)} "
                f"(from {self._format_duration(old_remaining)} to {self._format_duration(new_remaining)} remaining)."
            )
            self.logger.info(
                "security.totp_unlock_window_extended",
                extra={
                    "platform": event.platform,
                    "user_id": event.author_id,
                    "scope": realm,
                    "extend_seconds": ttl_seconds,
                    "old_remaining_seconds": old_remaining,
                    "new_remaining_seconds": new_remaining,
                },
            )
        await self.reply(sink, "\n".join(lines))

    def _format_unlock_status_line(self, event: MessageEvent) -> str:
        default_remaining = self._totp_unlock_remaining(event, _UNLOCK_SCOPE_DEFAULT)
        gh_remaining = self._totp_unlock_remaining(event, _UNLOCK_SCOPE_GH)
        default_text = f"{self._format_duration(default_remaining)} remaining" if default_remaining > 0 else "locked"
        gh_text = f"{self._format_duration(gh_remaining)} remaining" if gh_remaining > 0 else "locked"
        return f"Unlocks: default {default_text}, gh {gh_text}"

    def _normalize_unlock_totp_syntax(self, cmdline: str) -> str:
        parts = cmdline.split()
        if not parts or parts[0].lower() not in {"unlock", "ul"}:
            return cmdline
        if _TOTP_ARG_RE.search(cmdline):
            return cmdline
        index = 1
        if len(parts) <= index:
            return cmdline
        if parts[index].lower() in {"all", _UNLOCK_SCOPE_DEFAULT, _UNLOCK_SCOPE_GH}:
            index += 1
            if len(parts) <= index:
                return cmdline
        if re.fullmatch(r"\d{6}", parts[index]):
            parts.insert(index, "--totp")
            return " ".join(parts)
        return cmdline

    def _totp_unlock_scope_key(self, event: MessageEvent, scope: str = _UNLOCK_SCOPE_DEFAULT) -> str:
        return f"{event.platform}:{event.author_id}:{scope}"

    def _totp_unlock_remaining(self, event: MessageEvent, scope: str = _UNLOCK_SCOPE_DEFAULT) -> int:
        key = self._totp_unlock_scope_key(event, scope)
        until = self._totp_unlock_until.get(key, 0.0)
        now = time.time()
        if until <= now:
            self._totp_unlock_until.pop(key, None)
            return 0
        return max(0, int(until - now))

    def _totp_is_unlocked(self, event: MessageEvent, scope: str = _UNLOCK_SCOPE_DEFAULT) -> bool:
        return self._totp_unlock_remaining(event, scope) > 0

    def _set_totp_unlock(self, event: MessageEvent, scope: str, ttl_seconds: int) -> None:
        key = self._totp_unlock_scope_key(event, scope)
        self._totp_unlock_until[key] = time.time() + max(1, ttl_seconds)
        self.logger.info(
            "security.totp_unlock_window_set",
            extra={
                "platform": event.platform,
                "channel_id": event.channel_id,
                "is_dm": event.is_dm,
                "user_id": event.author_id,
                "scope": scope,
                "ttl_seconds": ttl_seconds,
            },
        )

    def _clear_totp_unlock(self, event: MessageEvent, scope: str) -> None:
        key = self._totp_unlock_scope_key(event, scope)
        self._totp_unlock_until.pop(key, None)
        self.logger.info(
            "security.totp_unlock_window_cleared",
            extra={
                "platform": event.platform,
                "channel_id": event.channel_id,
                "is_dm": event.is_dm,
                "user_id": event.author_id,
                "scope": scope,
            },
        )

    def _parse_unlock_ttl_seconds(self, text: str) -> int:
        raw = (text or "").strip()
        if not raw:
            return _DEFAULT_UNLOCK_SECONDS
        match = _UNLOCK_TTL_RE.match(raw)
        if not match:
            raise ValueError("Unlock ttl must be like 30m, 1h, or 2h.")
        value = int(match.group(1))
        if value <= 0:
            raise ValueError("Unlock ttl must be greater than 0.")
        unit = match.group(2).lower()
        mult = {"m": 60, "h": 3600, "d": 86400}[unit]
        return value * mult

    def _format_duration(self, seconds: int) -> str:
        total = max(0, int(seconds))
        if total < 60:
            return f"{total}s"
        minutes, secs = divmod(total, 60)
        if minutes < 60:
            return f"{minutes}m" if secs == 0 else f"{minutes}m{secs}s"
        hours, mins = divmod(minutes, 60)
        if hours < 24:
            return f"{hours}h" if mins == 0 else f"{hours}h{mins}m"
        days, hrs = divmod(hours, 24)
        return f"{days}d" if hrs == 0 else f"{days}d{hrs}h"

    def _extract_totp_arg(self, text: str) -> tuple[str, str]:
        match = _TOTP_ARG_RE.search(text)
        if not match:
            return "", text.strip()
        code = match.group(1)
        cleaned = _TOTP_ARG_RE.sub(" ", text, count=1)
        cleaned = " ".join(cleaned.strip().split())
        return code, cleaned

    def _totp_user_key(self, event: MessageEvent) -> str:
        return f"{event.platform}:{event.author_id}"

    def _reset_all_confirm_key(self, event: MessageEvent) -> str:
        return f"{event.platform}:{event.author_id}"

    def begin_reset_all_confirmation(self, event: MessageEvent, ttl_seconds: int = _RESET_ALL_CONFIRM_TTL_SECONDS) -> int:
        key = self._reset_all_confirm_key(event)
        ttl = max(1, int(ttl_seconds))
        self._reset_all_confirm_until[key] = time.time() + ttl
        return ttl

    def consume_reset_all_confirmation(self, event: MessageEvent) -> bool:
        key = self._reset_all_confirm_key(event)
        until = self._reset_all_confirm_until.get(key, 0.0)
        if until <= time.time():
            self._reset_all_confirm_until.pop(key, None)
            return False
        self._reset_all_confirm_until.pop(key, None)
        return True

    def has_reset_all_confirmation_pending(self, event: MessageEvent) -> bool:
        key = self._reset_all_confirm_key(event)
        until = self._reset_all_confirm_until.get(key, 0.0)
        if until <= time.time():
            self._reset_all_confirm_until.pop(key, None)
            return False
        return True

    def clear_reset_all_confirmation(self, event: MessageEvent) -> None:
        key = self._reset_all_confirm_key(event)
        self._reset_all_confirm_until.pop(key, None)

    async def _reply_totp_locked(self, sink: ResponseSink, retry_after_seconds: int) -> None:
        await self.reply_forbidden(
            sink,
            f"Too many invalid TOTP attempts. Retry in {max(1, int(retry_after_seconds))}s.",
        )

    def _log_totp_event(
        self,
        level: str,
        event_name: str,
        event: MessageEvent,
        command_name: str,
        **extra: Any,
    ) -> None:
        payload = {
            "platform": event.platform,
            "channel_id": event.channel_id,
            "is_dm": event.is_dm,
            "user_id": event.author_id,
            "command": command_name,
        }
        payload.update(extra)
        if level == "warning":
            self.logger.warning(event_name, extra=payload)
            return
        self.logger.info(event_name, extra=payload)

    async def require_totp(
        self,
        event: MessageEvent,
        sink: ResponseSink,
        command_name: str,
        text: str,
    ) -> tuple[bool, str]:
        """Enforce TOTP verification and return sanitized command text."""
        if not self._totp_enabled(event):
            return True, text
        user_key = self._totp_user_key(event)
        allowed, retry_after = self._totp_limiter.check_allowed(user_key)
        if allowed and user_key in self._totp_locked_users:
            self._totp_locked_users.discard(user_key)
            self._log_totp_event("info", "security.totp_unlock", event, command_name)
        if not allowed:
            self._totp_locked_users.add(user_key)
            self._log_totp_event(
                "warning",
                "security.totp_locked",
                event,
                command_name,
                retry_after_seconds=retry_after,
                reason="cooldown_active",
            )
            await self._reply_totp_locked(sink, retry_after)
            return False, text
        code, cleaned = self._extract_totp_arg(text)
        if not code:
            detail = f"TOTP required for '{command_name}'. Add `--totp 123456` to the command."
            if command_name == "unlock":
                detail = (
                    "TOTP required for 'unlock'. Use `!c unlock <totp> [ttl]`, "
                    "`!c unlock gh <totp> [ttl]`, or append `--totp 123456`."
                )
            await self.reply_forbidden(
                sink,
                detail,
            )
            return False, text
        env_name = self.cfg.discord.totp_secret_env
        secret = os.getenv(env_name, "").strip()
        if not secret:
            await self.reply_forbidden(sink, f"TOTP secret env {env_name!r} is not set.")
            return False, text
        matched_step = verify_totp(code, secret, window=self.cfg.discord.totp_window)
        if matched_step is None:
            lock_seconds = self._totp_limiter.record_failure(user_key)
            if lock_seconds > 0:
                self._totp_locked_users.add(user_key)
                self._log_totp_event(
                    "warning",
                    "security.totp_locked",
                    event,
                    command_name,
                    retry_after_seconds=lock_seconds,
                    reason="invalid_code_threshold",
                )
                await self._reply_totp_locked(sink, lock_seconds)
            else:
                self._log_totp_event("warning", "security.totp_invalid", event, command_name)
                await self.reply_forbidden(sink, "Invalid TOTP code.")
            return False, text
        last = self._totp_last_step_by_user.get(user_key, -1)
        if matched_step <= last:
            lock_seconds = self._totp_limiter.record_failure(user_key)
            if lock_seconds > 0:
                self._totp_locked_users.add(user_key)
                self._log_totp_event(
                    "warning",
                    "security.totp_locked",
                    event,
                    command_name,
                    retry_after_seconds=lock_seconds,
                    reason="replay_threshold",
                )
                await self._reply_totp_locked(sink, lock_seconds)
            else:
                self._log_totp_event("warning", "security.totp_replay", event, command_name)
                await self.reply_forbidden(sink, "TOTP code already used; wait for a new code and retry.")
            return False, text
        self._totp_limiter.record_success(user_key)
        self._totp_last_step_by_user[user_key] = matched_step
        self._log_totp_event("info", "security.totp_success", event, command_name)
        return True, cleaned

    def dm_binding_key(self, event: MessageEvent) -> str:
        """Return a stable key for DM repo bindings."""
        return f"{event.platform}:{event.channel_id}"

    def get_dm_binding(self, event: MessageEvent) -> str:
        """Return the bound repo name for a DM, if any."""
        state = self.state.load()
        raw = (state.dm_bindings.get(self.dm_binding_key(event), "") or "").strip()
        if not raw:
            return ""
        try:
            return pathutil.normalize_repo_name(raw)
        except ValueError:
            return raw.lower()

    def set_dm_binding(self, event: MessageEvent, repo_name: str) -> None:
        """Set the bound repo name for a DM."""
        repo_name = pathutil.normalize_repo_name(repo_name)
        key = self.dm_binding_key(event)
        self.state.update(lambda fs: fs.dm_bindings.__setitem__(key, repo_name))

    def clear_dm_binding(self, event: MessageEvent) -> None:
        """Clear the bound repo name for a DM."""
        key = self.dm_binding_key(event)
        self.state.update(lambda fs: fs.dm_bindings.pop(key, None))

    def _transport_user_allowed(self, event: MessageEvent) -> bool:
        if event.platform != "discord":
            return False
        if not self.cfg.discord.allowed_user_ids:
            return False
        return event.author_id in self.cfg.discord.allowed_user_ids

    def _discord_repo_channel_is_private(self, event: MessageEvent) -> bool:
        """Return True when a Discord room is private from @everyone."""
        if event.platform != "discord" or event.is_dm:
            return True
        message = event.raw_event
        channel = getattr(message, "channel", None) if message is not None else None
        if channel is None:
            self.logger.warning(
                "routing.discord_privacy_unknown",
                extra={"channel_id": event.channel_id, "reason": "missing_channel"},
            )
            return False

        channel_type = getattr(channel, "type", None)
        if getattr(channel_type, "name", "") == "private_thread" or str(channel_type) == "private_thread":
            return True

        guild = getattr(channel, "guild", None)
        default_role = getattr(guild, "default_role", None) if guild is not None else None
        permissions_for = getattr(channel, "permissions_for", None)
        if default_role is None or not callable(permissions_for):
            self.logger.warning(
                "routing.discord_privacy_unknown",
                extra={"channel_id": event.channel_id, "reason": "missing_permissions"},
            )
            return False
        try:
            perms = permissions_for(default_role)
        except Exception as exc:
            self.logger.warning(
                "routing.discord_privacy_unknown",
                extra={"channel_id": event.channel_id, "reason": "permissions_error", "error": str(exc)},
            )
            return False
        view_channel = getattr(perms, "view_channel", None)
        if isinstance(view_channel, bool):
            return not view_channel
        self.logger.warning(
            "routing.discord_privacy_unknown",
            extra={"channel_id": event.channel_id, "reason": "missing_view_channel"},
        )
        return False

    def _transport_prefix(self, event: MessageEvent) -> str:
        _ = event
        return self.cfg.discord.prefix or "!c"

    def _transport_allow_plain_prompts(self, event: MessageEvent) -> bool:
        _ = event
        return self.cfg.discord.allow_plain_prompts

    async def handle_upload_request(self, event: MessageEvent, sink: ResponseSink, repo_name: str, repo_path: str) -> None:
        """Prompt for a destination path for uploaded files."""
        await self.file_transfers.handle_upload_request(event, sink, repo_name, repo_path, self.reply_forbidden, self.reply)

    async def handle_pending_upload_response(
        self,
        event: MessageEvent,
        sink: ResponseSink,
        repo_name: str,
        content_override: str | None = None,
    ) -> bool:
        """Handle a pending upload path response."""
        return await self.file_transfers.handle_pending_upload_response(
            event,
            sink,
            repo_name,
            self._transport_prefix(event),
            self.reply_forbidden,
            self.reply,
            content_override,
        )

    @asynccontextmanager
    async def typing_context(self, sink: ResponseSink):
        """Provide a typing indicator context."""
        if sink.capabilities().typing:
            async with sink.typing():
                yield
            return
        async with null_typing():
            yield

    async def update_pinned_status(self, sink: ResponseSink, user_id: str, session: str) -> None:
        """Update or pin the current session status message."""
        sess = session or DEFAULT_SESSION
        model = self.session_model(sink.channel_id, sess)
        reasoning = self.session_reasoning_effort(sink.channel_id, sess)
        model_info = f" model {model}" if model else ""
        show_reasoning = bool(self._runtime_option_value(sink.channel_id, "show_reasoning_details"))
        reasoning_info = f" reasoning {reasoning}" if show_reasoning and reasoning else ""
        text = f"User {user_id} current session: {sess}{model_info}{reasoning_info}"
        await sink.update_pinned_status(user_id, session, text)

    def seed_agents_template(self, repo_path: str) -> None:
        """Seed AGENTS.md from a template when configured."""
        tmpl = (self.cfg.repo_bootstrap.agents_template or "").strip()
        if not tmpl:
            return
        agents_path = os.path.join(repo_path, "AGENTS.md")
        if os.path.exists(agents_path):
            return
        data = Path(tmpl).read_text(encoding="utf-8")
        Path(agents_path).write_text(data, encoding="utf-8")

    def spec_prompt(self, repo_name: str) -> str:
        """Render the spec capture prompt template."""
        prompt = (self.cfg.repo_bootstrap.spec_prompt or "").strip()
        if not prompt:
            prompt = "Please ask me for a project spec."
        return prompt.replace("{{REPO_NAME}}", repo_name)

    async def repo_busy(self, repo_name: str) -> bool:
        """Return True if a repo has active or queued jobs."""
        repo_key = self._repo_key(repo_name)
        state = self.state.load()
        for channel_id, ch in state.channels.items():
            for sess in ch.sessions.values():
                if self._repo_key(sess.repo_name) == repo_key:
                    if await self.has_active(channel_id):
                        return True
                    statuses = await self.coordinator.snapshot(channel_id)
                    if statuses:
                        return True
        return False

    def _repo_key(self, repo_name: str) -> str:
        raw = (repo_name or "").strip()
        if not raw:
            return ""
        try:
            return pathutil.normalize_repo_name(raw)
        except ValueError:
            return raw.lower()

    def _append_codex_error_log(
        self,
        channel_id: str,
        session: str,
        repo_name: str,
        repo_path: str,
        args: list[str],
        return_code: Optional[int],
        stderr_lines: list[str],
        note: str,
    ) -> None:
        if not self._codex_error_log_path:
            return
        try:
            os.makedirs(os.path.dirname(self._codex_error_log_path), exist_ok=True)
            payload = {
                "timestamp": utc_now_iso(),
                "channel_id": channel_id,
                "session": session or DEFAULT_SESSION,
                "repo_name": repo_name,
                "repo_path": repo_path,
                "return_code": return_code,
                "note": note,
                "args": args,
                "stderr_tail": list(stderr_lines[-20:]),
            }
            with open(self._codex_error_log_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(payload, ensure_ascii=True) + "\n")
            self._session_log.append(
                channel_id,
                session or DEFAULT_SESSION,
                "codex.error",
                payload,
                repo_name=repo_name,
            )
        except Exception as exc:
            self.logger.warning("codex.error_log_write_failed", extra={"error": str(exc)})

    def audit_start(self, channel_id: str, session: str, thread_id: str, meta: Any) -> Optional[Entry]:
        """Start an audit entry with error handling."""
        return self._audit_helper.start(channel_id, session, thread_id, meta)

    def append_audit_codex(self, entry: Optional[Entry], line: str) -> None:
        """Append a JSONL line to the audit log."""
        self._audit_helper.append_codex(entry, line)

    def append_audit_output(self, entry: Optional[Entry], msg: str) -> None:
        """Append a message to the audit log."""
        self._audit_helper.append_output(entry, msg)

    def append_audit_stderr(self, entry: Optional[Entry], msg: str) -> None:
        """Append stderr output to the audit log."""
        self._audit_helper.append_stderr(entry, msg)

    def close_audit(self, entry: Optional[Entry]) -> None:
        """Close an audit entry safely."""
        self._audit_helper.close(entry)

    def update_state(
        self,
        channel_id: str,
        session: str,
        repo_name: str,
        repo_path: str,
        thread_id: str,
        model: str,
        reasoning_effort: str,
    ) -> None:
        """Update persistent state for a session."""
        self.coordinator.update_state(channel_id, session, repo_name, repo_path, thread_id, model, reasoning_effort)

    def session_model(self, channel_id: str, session: str) -> str:
        """Return model override for a session or fallback to default."""
        return self.coordinator.session_model(channel_id, session)

    def session_reasoning_effort(self, channel_id: str, session: str) -> str:
        """Return reasoning effort override for a session or fallback to default."""
        return self.coordinator.session_reasoning_effort(channel_id, session)

    def set_session_model(
        self,
        channel_id: str,
        session: str,
        repo_name: str,
        repo_path: str,
        model: str,
        reasoning_effort: str,
    ) -> None:
        """Set model and reasoning overrides for a session."""
        self.coordinator.set_session_model(channel_id, session, repo_name, repo_path, model, reasoning_effort)

    def update_usage(self, channel_id: str, session: str, evt: Event) -> None:
        """Update usage counters from a Codex event."""
        usage = usage_from_event(evt)
        if not usage:
            return
        session = session or DEFAULT_SESSION
        if channel_id not in self._usage:
            self._usage[channel_id] = {}
        stats = self._usage[channel_id].get(session) or UsageStats()
        stats.input_tokens += usage.input_tokens
        stats.output_tokens += usage.output_tokens
        stats.total_tokens += usage.total_tokens or (usage.input_tokens + usage.output_tokens)
        self._usage[channel_id][session] = stats

    def get_usage(self, channel_id: str, session: str) -> Optional[UsageStats]:
        """Return usage stats for a session if present."""
        return self._usage.get(channel_id, {}).get(session)

    def update_activity(self, channel_id: str, session: str) -> None:
        """Record last output time for a session."""
        self.coordinator.update_activity(channel_id, session or DEFAULT_SESSION)

    def get_activity(self, channel_id: str, session: str) -> Optional[str]:
        """Return last output time for a session."""
        return self.coordinator.get_activity(channel_id, session or DEFAULT_SESSION)

    def clear_session_thread(self, channel_id: str, session: str) -> bool:
        """Clear stored thread id for a session when resume thread is stale."""
        return self.coordinator.clear_session_thread(channel_id, session or DEFAULT_SESSION)

    async def set_active(self, channel_id: str, session: str, proc: Any) -> None:
        """Track a running Codex process for a session."""
        await self.coordinator.set_active(channel_id, session or DEFAULT_SESSION, proc)

    async def clear_active(self, channel_id: str, session: str) -> None:
        """Clear the running process for a session."""
        await self.coordinator.clear_active(channel_id, session or DEFAULT_SESSION)

    async def get_active(self, channel_id: str, session: str) -> Optional[Any]:
        """Return the running process for a session, if any."""
        return await self.coordinator.get_active(channel_id, session or DEFAULT_SESSION)

    async def has_active(self, channel_id: str) -> bool:
        """Return True if any session is active in a channel."""
        return await self.coordinator.has_active(channel_id)

    async def active_sessions(self, channel_id: str) -> list[str]:
        """Return active session names for a channel."""
        return await self.coordinator.active_sessions(channel_id)

    async def consume_pending(self, channel_id: str, session: str) -> Optional[PendingConflict]:
        """Consume a pending conflict if present and not expired."""
        return await self.coordinator.consume_pending(channel_id, session)

    def current_session_for_user(self, user_id: str, channel_id: str, default_session: str = DEFAULT_SESSION) -> str:
        """Return sticky session selection for a user or default."""
        return self.coordinator.current_session_for_user(user_id, channel_id, default_session)

    def default_session_for_event(self, event: MessageEvent) -> str:
        """Return implicit default session for this event context."""
        if event.platform != "discord" or event.is_dm or not event.platform_thread_id:
            return DEFAULT_SESSION
        message = event.raw_event
        channel = getattr(message, "channel", None) if message is not None else None
        thread_name = str(getattr(channel, "name", "") or "").strip()
        return normalize_thread_session_name(thread_name)

    def current_session_for_event(self, event: MessageEvent) -> str:
        """Return sticky session or context-aware default for a message event."""
        default_session = self.default_session_for_event(event)
        if event.is_dm:
            return self.current_session_for_user(event.author_id, event.channel_id, default_session)
        return self._single_known_scope_session(event.channel_id) or default_session

    def resolve_scoped_session_for_event(self, event: MessageEvent, requested_session: str) -> str:
        """Enforce single-session-per-scope semantics for channel/thread usage."""
        requested = normalize_session(requested_session or "")
        if event.is_dm:
            return requested or DEFAULT_SESSION
        scoped = self.default_session_for_event(event)
        known = self._single_known_scope_session(event.channel_id)
        if not requested:
            return known or scoped
        if requested == scoped:
            return scoped
        if known and requested == known:
            return known
        if requested and requested != scoped:
            raise ValueError(f"This scope supports a single session '{scoped}'.")
        return known or scoped

    def _single_known_scope_session(self, channel_id: str) -> str:
        names: set[str] = set()
        state = self.state.load()
        ch = state.channels.get(channel_id)
        if ch:
            names.update(ch.sessions.keys())
        names.update(self._awaiting_input.get(channel_id, {}).keys())
        if len(names) == 1:
            return next(iter(names))
        return ""
