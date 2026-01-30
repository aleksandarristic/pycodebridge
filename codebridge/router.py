"""Codex command router and handlers."""

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, Optional

from . import config as cfgmod
from .audit import Entry, Logger as AuditLogger
from .codex import Event, Options, Runner, display_texts, parse_event
from .session_coordinator import SessionCoordinator
from .state import Store, utc_now_iso
from .transport import Capabilities, MessageEvent, ResponseSink, null_typing
from .util import path as pathutil
from .handlers import core as core_handlers
from .handlers import dm_admin as dm_admin_handlers
from .handlers import git_helpers as git_handlers
from .handlers import repo_helpers as repo_handlers
from . import command_registry
from .file_transfer import FileTransferService
from .util.ansi import strip_control_codes
from .util.chunk import chunk_text
from .util.prompt import needs_user_input
from .router_helpers import (
    DEFAULT_SESSION,
    MAX_SESSIONS_PER_CHANNEL,
    PendingConflict,
    UsageStats,
    existing_thread,
    forbidden_message,
    normalize_session,
    pending_key,
    usage_from_event,
)
from .router_status import format_current_selection_line, format_session_line




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

        repo_name = match.group(1)
        prefix = self._transport_prefix(event)
        content = (event.content or "").strip()
        if event.attachments:
            try:
                repo_path = pathutil.resolve_repo_path(self.cfg.codex.code_root, repo_name)
            except Exception as exc:
                await self.reply_forbidden(sink, f"Repo error: {exc}")
                return
            await self.handle_upload_request(event, sink, repo_name, repo_path)
            return
        if await self.handle_pending_upload_response(event, sink, repo_name):
            return
        if not content.startswith(prefix):
            if not self._transport_allow_plain_prompts(event):
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

        if await self.handle_pending_upload_response(event, sink, repo_name):
            return

        fields = cmdline.split()
        cmd = fields[0].lower()
        rest = cmdline[len(fields[0]) :].strip()
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

    def config_text(self) -> str:
        """Render a concise config summary."""
        cfg = self.cfg
        return (
            f"code_root: {cfg.codex.code_root}\n"
            f"sandbox: {cfg.codex.sandbox}\n"
            f"model: {cfg.codex.model}\n"
            f"model_reasoning_effort: {cfg.codex.model_reasoning_effort}\n"
            f"prefix: {cfg.discord.prefix}\n"
            f"allow_plain_prompts: {cfg.discord.allow_plain_prompts}\n"
            f"channel regex: {cfg.discord.channel_name_regex}\n"
            f"allowed_user_ids: {len(cfg.discord.allowed_user_ids)}\n"
            f"dm_admin_enabled: {cfg.discord.dm_admin_enabled}\n"
            f"dm_admin_user_ids: {len(cfg.discord.dm_admin_user_ids)}"
        )

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
        entry = self.audit_start(channel_id, session or DEFAULT_SESSION, "pending", meta)
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
                        on_stderr=lambda line: self.append_audit_stderr(entry, line),
                        on_exit=lambda err, rc: self.on_exit(channel_id, session, repo_name, err, rc),
                    )
                )
            except Exception as exc:
                self.close_audit(entry)
                raise exc

            await self.set_active(channel_id, session, proc)
            try:
                rc = await proc.wait()
                if rc != 0:
                    self.logger.warning("codex.exit", extra={"channel_id": channel_id, "repo": repo_name, "session": session, "code": rc})
            finally:
                await self.clear_active(channel_id, session)
                self.close_audit(entry)

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
        self.append_audit_codex(entry, line)
        evt = parse_event(line)
        if not evt:
            text = strip_control_codes(line).strip()
            if text and relay_output:
                for chunk in chunk_text(text, self.cfg.discord.max_discord_message_chars):
                    self.append_audit_output(entry, chunk)
                    await self.reply(sink, chunk)
            return
        self.update_usage(channel_id, session, evt)
        self.update_activity(channel_id, session)
        for msg in display_texts(evt):
            text = strip_control_codes(msg)
            if needs_user_input(text):
                text = f"Codex asks: {text}"
            if relay_output:
                for chunk in chunk_text(text, self.cfg.discord.max_discord_message_chars):
                    self.append_audit_output(entry, chunk)
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
        if err:
            self.logger.error("codex.exit", extra={"channel_id": channel_id, "repo": repo_name, "session": session, "error": str(err)})
            return
        self.logger.info("codex.exit", extra={"channel_id": channel_id, "repo": repo_name, "session": session, "code": rc})

    async def reply(self, sink: ResponseSink, content: str) -> None:
        """Send a reply to a channel, chunking as needed."""
        content = strip_control_codes(content)
        for chunk in chunk_text(content, self.cfg.discord.max_discord_message_chars):
            await sink.send(chunk)

    async def reply_forbidden(self, sink: ResponseSink, detail: str) -> None:
        """Send a standardized forbidden/invalid response."""
        await sink.send(forbidden_message(detail))

    def _dm_admin_allowed(self, user_id: str) -> bool:
        if self.cfg.discord.dm_admin_user_ids:
            return user_id in self.cfg.discord.dm_admin_user_ids
        return user_id in self.cfg.discord.allowed_user_ids

    def dm_binding_key(self, event: MessageEvent) -> str:
        """Return a stable key for DM repo bindings."""
        return f"{event.platform}:{event.channel_id}"

    def get_dm_binding(self, event: MessageEvent) -> str:
        """Return the bound repo name for a DM, if any."""
        state = self.state.load()
        return state.dm_bindings.get(self.dm_binding_key(event), "")

    def set_dm_binding(self, event: MessageEvent, repo_name: str) -> None:
        """Set the bound repo name for a DM."""
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

    async def handle_pending_upload_response(self, event: MessageEvent, sink: ResponseSink, repo_name: str) -> bool:
        """Handle a pending upload path response."""
        return await self.file_transfers.handle_pending_upload_response(
            event,
            sink,
            repo_name,
            self._transport_prefix(event),
            self.reply_forbidden,
            self.reply,
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
        if event.platform == "telegram" and not thread_id:
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
        state = self.state.load()
        for channel_id, ch in state.channels.items():
            for sess in ch.sessions.values():
                if sess.repo_name == repo_name:
                    if await self.has_active(channel_id):
                        return True
                    statuses = await self.coordinator.snapshot(channel_id)
                    if statuses:
                        return True
        return False

    def audit_start(self, channel_id: str, session: str, thread_id: str, meta: Any) -> Optional[Entry]:
        """Start an audit entry with error handling."""
        if not self.audit:
            return None
        try:
            return self.audit.start(channel_id, session, thread_id, meta)
        except Exception as exc:
            self.logger.error("audit.start_failed", extra={"channel_id": channel_id, "session": session, "error": str(exc)})
            return None

    def append_audit_codex(self, entry: Optional[Entry], line: str) -> None:
        """Append a JSONL line to the audit log."""
        if entry:
            try:
                entry.append_codex_line(line)
            except Exception:
                pass

    def append_audit_output(self, entry: Optional[Entry], msg: str) -> None:
        """Append a message to the audit log."""
        if entry:
            try:
                entry.append_discord_out(msg)
            except Exception:
                pass

    def append_audit_stderr(self, entry: Optional[Entry], msg: str) -> None:
        """Append stderr output to the audit log."""
        if entry:
            try:
                entry.append_stderr(msg)
            except Exception:
                pass

    def close_audit(self, entry: Optional[Entry]) -> None:
        """Close an audit entry safely."""
        if entry:
            try:
                entry.close()
            except Exception:
                pass

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
