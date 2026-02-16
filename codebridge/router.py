"""Codex command router and handlers."""

import os
import re
import subprocess
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, Optional, Set

from . import config as cfgmod
from .audit import Entry, Logger as AuditLogger
from .audit_helpers import AuditHelper
from .codex import Event, Options, Runner, display_texts, parse_event
from .session_coordinator import SessionCoordinator
from .state import Store, utc_now_iso
from .transport import Capabilities, MessageEvent, ResponseSink, null_typing
from .util import path as pathutil
from .handlers import core as core_handlers
from .handlers import dm_admin as dm_admin_handlers
from .handlers import gh_helpers as gh_handlers
from .handlers import git_helpers as git_handlers
from .handlers import repo_helpers as repo_handlers
from . import command_registry
from .file_transfer import FileTransferService
from .reply_helpers import send_forbidden, send_reply
from .util.ansi import strip_control_codes
from .util.chunk import chunk_text
from .util.prompt import needs_user_input
from .totp import TotpAttemptLimiter, verify_totp
from .router_helpers import (
    DEFAULT_SESSION,
    MAX_SESSIONS_PER_CHANNEL,
    PendingConflict,
    UsageStats,
    normalize_session,
    usage_from_event,
)
from .router_config import render_config_text
from .router_status import format_current_selection_line, format_session_line

_TOTP_ARG_RE = re.compile(r"(?:^|\s)--totp\s+(\d{6})(?=\s|$)")
_AWAITING_INPUT_TTL_SECONDS = 900
_DEFAULT_UNLOCK_SECONDS = 3600
_UNLOCK_TTL_RE = re.compile(r"^(\d+)\s*([mhd])$", re.IGNORECASE)
_READ_ONLY_COMMANDS = {
    "help",
    "status",
    "stats",
    "peek",
    "models",
    "showrepo",
    "showchanges",
    "ps",
}
_GIT_READ_ONLY_SUBCOMMANDS = {"status", "log", "branches", "show", "diff"}


def _git_commit_hash() -> str:
    try:
        root = Path(__file__).resolve().parents[1]
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
        self._awaiting_input: Dict[str, Dict[str, float]] = {}
        self._totp_last_step_by_user: Dict[str, int] = {}
        self._totp_locked_users: Set[str] = set()
        self._totp_unlock_until: Dict[str, float] = {}
        self._totp_limiter = TotpAttemptLimiter(
            max_failures=cfg.discord.totp_max_failures,
            window_seconds=cfg.discord.totp_failure_window_seconds,
            cooldown_seconds=cfg.discord.totp_cooldown_seconds,
        )

    async def handle_message(self, event: MessageEvent, sink: ResponseSink) -> None:
        """Handle an incoming message event."""
        if event.author_is_bot:
            return
        sink = self._contextual_sink(event, sink)

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
        if event.attachments:
            if self._totp_enabled(event):
                ok, _ = await self.require_totp(event, sink, "upload", content)
                if not ok:
                    return
            try:
                repo_path = pathutil.resolve_repo_path(self.cfg.codex.code_root, repo_name)
            except Exception as exc:
                await self.reply_forbidden(sink, f"Repo error: {exc}")
                return
            await self.handle_upload_request(event, sink, repo_name, repo_path)
            return
        pending_content = content
        if self.file_transfers.has_pending_upload(event) and self._totp_enabled(event):
            ok, pending_content = await self.require_totp(event, sink, "upload", content)
            if not ok:
                return
        if await self.handle_pending_upload_response(event, sink, repo_name, pending_content):
            return
        if not content.startswith(prefix):
            relay_session, ambiguous = await self.pending_input_session(event)
            if ambiguous:
                await self.reply_forbidden(
                    sink,
                    "Multiple sessions are waiting for input. Use `!c answer <session> -- <text>`.",
                )
                return
            if relay_session:
                relay_text = content.strip()
                if not relay_text:
                    return
                if self._totp_enabled(event) and not self._totp_is_unlocked(event):
                    ok, relay_text = await self.require_totp(event, sink, "answer", relay_text)
                    if not ok:
                        return
                await self.handle_answer(event, sink, relay_session, relay_text)
                return
            allow_plain = self._transport_allow_plain_prompts(event)
            if self._totp_enabled(event) and self._totp_is_unlocked(event):
                allow_plain = True
            if not allow_plain:
                return
            self.logger.info(
                "routing.prompt",
                extra={
                    "platform": event.platform,
                    "channel_id": event.channel_id,
                    "repo": repo_name,
                    "session": self.current_session_for_user(event.author_id, event.channel_id),
                },
            )
            prompt = content.strip()
            if not prompt:
                return
            if self._totp_enabled(event) and not self._totp_is_unlocked(event):
                ok, prompt = await self.require_totp(event, sink, "resume", prompt)
                if not ok:
                    return
            try:
                repo_path = pathutil.resolve_repo_path(self.cfg.codex.code_root, repo_name)
            except Exception as exc:
                await self.reply_forbidden(sink, f"Repo error: {exc}")
                return
            session = self.current_session_for_user(event.author_id, event.channel_id)
            await self.handle_resume(event, sink, repo_name, repo_path, session, prompt)
            return

        cmdline = content[len(prefix) :].strip()
        if not cmdline:
            return

        pending_cmdline = cmdline
        if self.file_transfers.has_pending_upload(event) and self._totp_enabled(event):
            ok, pending_cmdline = await self.require_totp(event, sink, "upload", cmdline)
            if not ok:
                return
        if await self.handle_pending_upload_response(event, sink, repo_name, pending_cmdline):
            return

        fields = cmdline.split()
        cmd = fields[0].lower()
        rest = cmdline[len(fields[0]) :].strip()
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
            effective_cmd = "/quit" if len(fields) >= 2 and fields[1] == "/quit" else cmd
        self.logger.info(
            "routing.command",
            extra={
                "platform": event.platform,
                "channel_id": event.channel_id,
                "repo": repo_name,
                "cmd": cmd,
                "session": self.current_session_for_user(event.author_id, event.channel_id),
                "user_id": event.author_id,
            },
        )
        if cmd == "createrepo":
            try:
                repo_path = pathutil.resolve_repo_path_for_create(self.cfg.codex.code_root, repo_name)
            except Exception as exc:
                await self.reply_forbidden(sink, f"Repo error: {exc}")
                return
            await self.handle_create_repo(event, sink, repo_name, repo_path)
            return

        try:
            repo_path = pathutil.resolve_repo_path(self.cfg.codex.code_root, repo_name)
        except Exception as exc:
            await self.reply_forbidden(sink, f"Repo error: {exc}")
            return

        if len(fields) >= 2 and fields[1] == "/quit":
            session_name = fields[0]
            try:
                session_name = normalize_session(session_name)
            except ValueError as exc:
                await self.reply_forbidden(sink, str(exc))
                return
            await self.handle_quit(sink, session_name)
            return
        if cmdline.startswith("/"):
            await self.handle_resume(event, sink, repo_name, repo_path, DEFAULT_SESSION, cmdline)
            return
        if len(fields) >= 2 and fields[1].startswith("/"):
            session_name = fields[0]
            try:
                session_name = normalize_session(session_name)
            except ValueError as exc:
                await self.reply_forbidden(sink, str(exc))
                return
            prompt = cmdline[len(fields[0]) :].strip()
            await self.handle_resume(event, sink, repo_name, repo_path, session_name, prompt)
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

        await self.handle_resume(event, sink, repo_name, repo_path, DEFAULT_SESSION, cmdline)

    async def handle_dm_message(self, event: MessageEvent, sink: ResponseSink) -> None:
        """Handle an incoming DM admin message."""
        await dm_admin_handlers.handle_dm_message(self, event, sink)

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
    ) -> None:
        """Resume a Codex session with a prompt."""
        await core_handlers.handle_resume(self, event, sink, repo_name, repo_path, session, prompt)

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

    async def handle_kill(self, sink: ResponseSink, session: str) -> None:
        """Force-kill a running Codex process."""
        await core_handlers.handle_kill(self, sink, session)

    async def handle_quit(self, sink: ResponseSink, session: str) -> None:
        """Send /quit to the Codex process."""
        await core_handlers.handle_quit(self, sink, session)

    async def handle_answer(self, event: MessageEvent, sink: ResponseSink, session: str, text: str) -> None:
        """Send an approval/input response to an active Codex session."""
        await core_handlers.handle_answer(self, event, sink, session, text)

    async def handle_wait(self, event: MessageEvent, sink: ResponseSink) -> None:
        """Show sessions currently awaiting user input from Codex prompts."""
        pending = self._prune_awaiting_input(event.channel_id)
        if not pending:
            await self.reply(sink, "No sessions are waiting for input.")
            return
        active: list[str] = []
        for session in sorted(pending.keys()):
            if await self.get_active(event.channel_id, session):
                active.append(session)
        if not active:
            await self.reply(sink, "No active sessions are waiting for input.")
            return
        await self.reply(sink, "Waiting for input: " + ", ".join(active))

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

    async def handle_gh(self, sink: ResponseSink, repo_path: str, rest: str) -> None:
        """Run gh helper commands."""
        await gh_handlers.handle_gh(self, sink, repo_path, rest)

    async def handle_download(self, sink: ResponseSink, repo_path: str, rel_path: str) -> None:
        """Send a file from the repo to the channel."""
        await self.file_transfers.handle_download(sink, repo_path, rel_path, self.reply_forbidden)

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
            lines.append(f"[{s.seq}] channel:{s.channel_id} session:{s.session} thread:{s.thread_id}")
        text = "\n".join(lines)
        for chunk in chunk_text(text, self.cfg.discord.max_discord_message_chars):
            await self.reply(sink, chunk)

    async def handle_ps(self, sink: ResponseSink) -> None:
        """Show queued/running jobs for the channel."""
        statuses = await self.coordinator.snapshot(sink.channel_id)
        if not statuses:
            await self.reply_forbidden(sink, "No jobs queued or running.")
            return
        lines = []
        for s in statuses:
            pos = f" pos:{s.position}" if s.position >= 0 else ""
            lines.append(f"{s.job_id} [{s.status}] session:{s.session or DEFAULT_SESSION}{pos} {s.command}")
        await self.reply(sink, "\n".join(lines))

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
        """Unlock non-high-risk commands for this user+chat for a TTL."""
        token = (rest or "").strip().lower()
        if token in {"status", "state"}:
            remaining = self._totp_unlock_remaining(event)
            if remaining <= 0:
                await self.reply(sink, "TOTP unlock is inactive.")
                return
            await self.reply(sink, f"TOTP unlock is active for {self._format_duration(remaining)}.")
            return
        try:
            ttl_seconds = self._parse_unlock_ttl_seconds(rest)
        except ValueError as exc:
            await self.reply_forbidden(sink, str(exc))
            return
        self._set_totp_unlock(event, ttl_seconds)
        await self.reply(
            sink,
            f"TOTP unlock active for {self._format_duration(ttl_seconds)} in this chat. "
            "High-risk commands still require --totp.",
        )

    async def handle_lock(self, event: MessageEvent, sink: ResponseSink) -> None:
        """Clear any active unlock for this user+chat."""
        self._clear_totp_unlock(event)
        await self.reply(sink, "TOTP unlock cleared for this chat.")

    async def handle_select_session(self, event: MessageEvent, sink: ResponseSink, session: str) -> None:
        """Set the sticky session selection for a user."""
        user_id = event.author_id
        channel_id = event.channel_id
        self.coordinator.set_sticky(channel_id, user_id, session)
        await self.update_state(channel_id, session, "", "", "", "", "")
        await self.reply(sink, f"Using session '{session}' by default.")
        await self.update_pinned_status(sink, user_id, session)

    async def handle_thread(self, sink: ResponseSink, session: str, repo_name: str, repo_path: str, thread_id: str) -> None:
        """Override stored thread id for a session."""
        session = normalize_session(session or DEFAULT_SESSION)
        self.update_state(sink.channel_id, session, repo_name, repo_path, thread_id, "", "")
        await self.reply(sink, f"Thread id for session '{session}' set to {thread_id}")

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

    async def send_status(self, sink: ResponseSink, repo_name: str, repo_path: str) -> None:
        """Send status summary for the channel and sessions."""
        state = self.state.load()
        ch = state.channels.get(sink.channel_id)
        if ch and ch.sessions:
            lines = [f"Repo: {repo_name}", f"Path: {repo_path}", f"Sessions ({len(ch.sessions)}/{MAX_SESSIONS_PER_CHANNEL}):"]
            for name, sess in ch.sessions.items():
                active = await self.get_active(sink.channel_id, name) is not None
                lines.append(
                    format_session_line(
                        name,
                        sess,
                        active,
                        self.cfg.codex.model,
                        self.cfg.codex.model_reasoning_effort,
                    )
                )
            current = self.current_session_for_user("", sink.channel_id)
            if current:
                current_model = self.session_model(sink.channel_id, current)
                current_reasoning = self.session_reasoning_effort(sink.channel_id, current)
                lines.append(format_current_selection_line(current, current_model, current_reasoning))
            await self.reply(sink, "\n".join(lines))
            return
        await self.reply(sink, f"Repo: {repo_name}\nPath: {repo_path}\nNo session attached.")

    async def send_help(self, sink: ResponseSink) -> None:
        """Send help text for supported commands."""
        await self.reply(sink, command_registry.render_help(self._command_specs))

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
        meta = {
            "repo_name": repo_name,
            "repo_path": repo_path,
            "args": args,
            "model": model,
            "reasoning_effort": reasoning_effort,
            "timestamp": utc_now_iso(),
            "channel": channel_id,
        }
        entry = self._audit_helper.start(channel_id, session or DEFAULT_SESSION, "pending", meta)
        stderr_tail: list[str] = []

        async def _on_stderr(line: str) -> None:
            self._audit_helper.append_stderr(entry, line)
            text = strip_control_codes((line or "").strip())
            if not text:
                return
            stderr_tail.append(text)
            if len(stderr_tail) > 5:
                del stderr_tail[: len(stderr_tail) - 5]

        async with self.typing_context(sink):
            try:
                proc = await self.runner.run(
                    Options(
                        repo_path=repo_path,
                        args=args,
                        env=self.cfg.codex.env,
                        on_jsonl=lambda line: self.on_jsonl(sink, channel_id, session, entry, line, relay_output),
                        on_thread=lambda tid: self.on_thread(
                            channel_id, session, repo_name, repo_path, model, reasoning_effort, entry, tid
                        ),
                        on_output=on_output,
                        on_stderr=_on_stderr,
                        on_exit=lambda err, rc: self.on_exit(channel_id, session, repo_name, err, rc),
                    )
                )
            except Exception as exc:
                self._audit_helper.close(entry)
                await self.reply_forbidden(sink, f"Codex failed to start: {exc}")
                return

            await self.set_active(channel_id, session, proc)
            try:
                rc = await proc.wait()
                if rc != 0:
                    self.logger.warning("codex.exit", extra={"channel_id": channel_id, "repo": repo_name, "session": session, "code": rc})
                    detail = f"Codex exited with code {rc}."
                    if stderr_tail:
                        detail += f" Last stderr: {stderr_tail[-1]}"
                    detail += " Use `!c logs` for details."
                    await self.reply_forbidden(sink, detail)
            finally:
                await self.clear_active(channel_id, session)
                self._audit_helper.close(entry)

    async def on_jsonl(
        self,
        sink: ResponseSink,
        channel_id: str,
        session: str,
        entry: Optional[Entry],
        line: str,
        relay_output: bool,
    ) -> None:
        """Handle a JSONL line from Codex and relay output."""
        self._audit_helper.append_codex(entry, line)
        evt = parse_event(line)
        if not evt:
            text = strip_control_codes(line).strip()
            if text and relay_output:
                for chunk in chunk_text(text, self.cfg.discord.max_discord_message_chars):
                    self._audit_helper.append_output(entry, chunk)
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
        self.update_state(channel_id, session, repo_name, repo_path, thread_id, model, reasoning_effort)

    async def on_exit(self, channel_id: str, session: str, repo_name: str, err: Optional[BaseException], rc: int) -> None:
        """Handle Codex process exit events."""
        await self.clear_active(channel_id, session)
        self.clear_awaiting_input(channel_id, session)
        if err:
            self.logger.error("codex.exit", extra={"channel_id": channel_id, "repo": repo_name, "session": session, "error": str(err)})
            return
        self.logger.info("codex.exit", extra={"channel_id": channel_id, "repo": repo_name, "session": session, "code": rc})

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
        preferred = self.current_session_for_user(event.author_id, event.channel_id) or DEFAULT_SESSION
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

    def _totp_required_for_command(self, event: MessageEvent, cmd: str, rest: str) -> bool:
        token = (cmd or "").strip().lower()
        if token in {"lock"}:
            return False
        if token in {"unlock"} and (rest or "").strip().lower() in {"status", "state"}:
            return False
        if token == "git" and self._git_subcommand(rest) in _GIT_READ_ONLY_SUBCOMMANDS:
            return False
        if self._totp_command_is_high_risk(token, rest):
            return True
        if token in _READ_ONLY_COMMANDS:
            return False
        if self._totp_is_unlocked(event):
            return False
        return True

    def _totp_command_is_high_risk(self, cmd: str, rest: str) -> bool:
        if cmd in {"createrepo", "clonerepo", "copyrepo", "deleterepo", "delete", "renamerepo", "rename", "gh"}:
            return True
        if cmd == "git":
            subcmd = self._git_subcommand(rest)
            if not subcmd:
                return True
            return subcmd not in _GIT_READ_ONLY_SUBCOMMANDS
        if cmd == "unlock":
            return True
        return False

    def _git_subcommand(self, rest: str) -> str:
        parts = (rest or "").split()
        if not parts:
            return ""
        return parts[0].strip().lower()

    def _totp_unlock_scope_key(self, event: MessageEvent) -> str:
        return f"{event.platform}:{event.channel_id}:{event.author_id}"

    def _totp_unlock_remaining(self, event: MessageEvent) -> int:
        key = self._totp_unlock_scope_key(event)
        until = self._totp_unlock_until.get(key, 0.0)
        now = time.time()
        if until <= now:
            self._totp_unlock_until.pop(key, None)
            return 0
        return max(0, int(until - now))

    def _totp_is_unlocked(self, event: MessageEvent) -> bool:
        return self._totp_unlock_remaining(event) > 0

    def _set_totp_unlock(self, event: MessageEvent, ttl_seconds: int) -> None:
        key = self._totp_unlock_scope_key(event)
        self._totp_unlock_until[key] = time.time() + max(1, ttl_seconds)
        self.logger.info(
            "security.totp_unlock_window_set",
            extra={
                "platform": event.platform,
                "channel_id": event.channel_id,
                "is_dm": event.is_dm,
                "user_id": event.author_id,
                "ttl_seconds": ttl_seconds,
            },
        )

    def _clear_totp_unlock(self, event: MessageEvent) -> None:
        key = self._totp_unlock_scope_key(event)
        self._totp_unlock_until.pop(key, None)
        self.logger.info(
            "security.totp_unlock_window_cleared",
            extra={
                "platform": event.platform,
                "channel_id": event.channel_id,
                "is_dm": event.is_dm,
                "user_id": event.author_id,
            },
        )

    def _parse_unlock_ttl_seconds(self, text: str) -> int:
        raw = (text or "").strip()
        if not raw:
            return _DEFAULT_UNLOCK_SECONDS
        match = _UNLOCK_TTL_RE.match(raw)
        if not match:
            raise ValueError("Usage: !c unlock --totp 123456 [ttl], where ttl is like 30m, 1h, or 2h.")
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
            await self.reply_forbidden(
                sink,
                f"TOTP required for '{command_name}'. Add `--totp 123456` to the command.",
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
        if event.platform == "telegram":
            if not self.cfg.telegram.allowed_user_ids:
                return True
            return event.author_id in self.cfg.telegram.allowed_user_ids
        if self.cfg.discord.allowed_user_ids and event.author_id not in self.cfg.discord.allowed_user_ids:
            return False
        return True

    def _transport_prefix(self, event: MessageEvent) -> str:
        if event.platform == "telegram":
            return self.cfg.telegram.prefix or "!c"
        return self.cfg.discord.prefix or "!c"

    def _transport_allow_plain_prompts(self, event: MessageEvent) -> bool:
        if event.platform == "telegram":
            return self.cfg.telegram.allow_plain_prompts
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
        reasoning_info = f" reasoning {reasoning}" if reasoning else ""
        text = f"User {user_id} current session: {sess}{model_info}{reasoning_info}"
        await sink.update_pinned_status(user_id, session, text)

    def _contextual_sink(self, event: MessageEvent, sink: ResponseSink) -> ResponseSink:
        thread_id = event.platform_thread_id or ""
        reply_to_id = ""
        if not thread_id and sink.capabilities().replies:
            reply_to_id = event.message_id or ""
        if not thread_id and not reply_to_id:
            return sink
        return _ThreadContextSink(sink, thread_id, reply_to_id)

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

    async def consume_pending(self, channel_id: str, session: str) -> Optional[PendingConflict]:
        """Consume a pending conflict if present and not expired."""
        return await self.coordinator.consume_pending(channel_id, session)

    def current_session_for_user(self, user_id: str, channel_id: str) -> str:
        """Return sticky session selection for a user or default."""
        return self.coordinator.current_session_for_user(user_id, channel_id)


class _ThreadContextSink:
    """Wrap a sink with thread/reply metadata for message sends."""

    def __init__(self, sink: ResponseSink, thread_id: str, reply_to_id: str) -> None:
        self._sink = sink
        self._thread_id = thread_id
        self._reply_to_id = reply_to_id
        self.channel_id = sink.channel_id

    async def send(self, content: str, thread_id: str | None = None, reply_to_id: str | None = None) -> None:
        caps = self._sink.capabilities()
        use_thread = thread_id or self._thread_id or None
        use_reply = reply_to_id or self._reply_to_id or None
        if not caps.threads:
            use_thread = None
        if not caps.replies:
            use_reply = None
        await self._sink.send(content, thread_id=use_thread, reply_to_id=use_reply)

    def capabilities(self) -> Capabilities:
        return self._sink.capabilities()

    def typing(self):  # type: ignore[override]
        return self._sink.typing()

    async def update_pinned_status(self, user_id: str, session: str, text: str) -> None:
        await self._sink.update_pinned_status(user_id, session, text)

    async def send_file(self, path: str, filename: str, thread_id: str | None = None, reply_to_id: str | None = None) -> None:
        caps = self._sink.capabilities()
        use_thread = thread_id or self._thread_id or None
        use_reply = reply_to_id or self._reply_to_id or None
        if not caps.threads:
            use_thread = None
        if not caps.replies:
            use_reply = None
        await self._sink.send_file(path, filename, thread_id=use_thread, reply_to_id=use_reply)
