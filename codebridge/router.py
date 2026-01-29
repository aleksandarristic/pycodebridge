"""Discord/Codex command router and handlers."""

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import discord

from . import config as cfgmod
from .audit import Entry, Logger as AuditLogger
from .codex import Event, Options, Runner, display_texts, parse_event
from .queue import Manager
from .session_service import SessionService
from .state import Store, utc_now_iso
from .util import path as pathutil
from .command_parse import (
    parse_choose,
    parse_session_and_id,
    parse_session_and_prompt,
    parse_session_or_limit,
)
from .handlers import core as core_handlers
from .handlers import dm_admin as dm_admin_handlers
from .handlers import git_helpers as git_handlers
from .handlers import repo_helpers as repo_handlers
from .util.ansi import strip_control_codes
from .util.chunk import chunk_text
from .util.prompt import needs_user_input
from .router_helpers import (
    DEFAULT_SESSION,
    FORBIDDEN_PREFIX,
    MAX_SESSIONS_PER_CHANNEL,
    PendingConflict,
    UsageStats,
    count_active_sessions,
    existing_thread,
    forbidden_message,
    normalize_session,
    pending_key,
    session_exists,
    set_sticky,
    usage_from_event,
)




class Router:
    """Main command router for Discord messages."""
    def __init__(self, cfg: cfgmod.Config, state: Store, audit: AuditLogger, runner: Runner, queue: Manager, logger):
        self.cfg = cfg
        self.state = state
        self.audit = audit
        self.runner = runner
        self.queue = queue
        self.logger = logger
        self._pins: Dict[str, int] = {}
        self._usage: Dict[str, Dict[str, UsageStats]] = {}
        self.sessions = SessionService(state, cfg)

    async def handle_message(self, client: discord.Client, message: discord.Message) -> None:
        """Handle an incoming Discord message."""
        if message.author.bot:
            return

        channel = message.channel
        is_dm = isinstance(channel, (discord.DMChannel, discord.GroupChannel))
        channel_name = channel.name if hasattr(channel, "name") and channel.name else str(channel.id)

        if is_dm:
            if not self.cfg.discord.dm_admin_enabled:
                return
            if not self._dm_admin_allowed(str(message.author.id)):
                await self.reply_forbidden(channel, "You are not allowed to use DM admin commands.")
                return
            await dm_admin_handlers.handle_dm_message(self, message)
            return

        if self.cfg.discord.guild_id and str(message.guild.id) != self.cfg.discord.guild_id:
            await self.reply_forbidden(channel, "This bot is not configured for this guild.")
            return

        if self.cfg.discord.allowed_user_ids and str(message.author.id) not in self.cfg.discord.allowed_user_ids:
            await self.reply_forbidden(channel, "You are not allowed to use this bot.")
            return

        rexp = self.cfg.channel_regex()
        match = rexp.match(channel_name)
        if not match:
            return

        repo_name = match.group(1)
        prefix = self.cfg.discord.prefix or "!c"
        content = (message.content or "").strip()
        if not content.startswith(prefix):
            if not self.cfg.discord.allow_plain_prompts:
                return
            prompt = content.strip()
            if not prompt:
                return
            try:
                repo_path = pathutil.resolve_repo_path(self.cfg.codex.code_root, repo_name)
            except Exception as exc:
                await self.reply_forbidden(channel, f"Repo error: {exc}")
                return
            session = self.current_session_for_user(str(message.author.id), str(channel.id))
            await self.handle_resume(message, repo_name, repo_path, session, prompt)
            return

        cmdline = content[len(prefix) :].strip()
        if not cmdline:
            return

        fields = cmdline.split()
        cmd = fields[0].lower()
        rest = cmdline[len(fields[0]) :].strip()
        if cmd == "createrepo":
            try:
                repo_path = pathutil.resolve_repo_path_for_create(self.cfg.codex.code_root, repo_name)
            except Exception as exc:
                await self.reply_forbidden(channel, f"Repo error: {exc}")
                return
            await self.handle_create_repo(message, repo_name, repo_path)
            return

        try:
            repo_path = pathutil.resolve_repo_path(self.cfg.codex.code_root, repo_name)
        except Exception as exc:
            await self.reply_forbidden(channel, f"Repo error: {exc}")
            return

        if len(fields) >= 2 and fields[1] == "/quit":
            session_name = fields[0]
            try:
                session_name = normalize_session(session_name)
            except ValueError as exc:
                await self.reply_forbidden(channel, str(exc))
                return
            await self.handle_quit(channel, session_name)
            return
        if cmdline.startswith("/"):
            await self.handle_resume(message, repo_name, repo_path, DEFAULT_SESSION, cmdline)
            return
        if len(fields) >= 2 and fields[1].startswith("/"):
            session_name = fields[0]
            try:
                session_name = normalize_session(session_name)
            except ValueError as exc:
                await self.reply_forbidden(channel, str(exc))
                return
            prompt = cmdline[len(fields[0]) :].strip()
            await self.handle_resume(message, repo_name, repo_path, session_name, prompt)
            return

        if cmd == "help":
            await self.send_help(channel)
            return
        if cmd == "status":
            await self.send_status(channel, repo_name, repo_path)
            return
        if cmd == "stats":
            session = rest.strip() or self.current_session_for_user(str(message.author.id), str(channel.id))
            try:
                session = normalize_session(session)
            except ValueError as exc:
                await self.reply_forbidden(channel, str(exc))
                return
            await self.handle_stats(channel, session)
            return
        if cmd == "peek":
            session = rest.strip() or self.current_session_for_user(str(message.author.id), str(channel.id))
            try:
                session = normalize_session(session)
            except ValueError as exc:
                await self.reply_forbidden(channel, str(exc))
                return
            await self.handle_peek(channel, session)
            return
        if cmd == "config":
            await self.reply(channel, self.config_text())
            return
        if cmd == "start":
            session_name, _ = parse_session_and_prompt(rest)
            if not session_name:
                session_name = self.current_session_for_user(str(message.author.id), str(channel.id))
            try:
                session_name = normalize_session(session_name)
            except ValueError as exc:
                await self.reply_forbidden(channel, str(exc))
                return
            await self.handle_start(message, repo_name, repo_path, session_name)
            return
        if cmd == "resume":
            session_name, prompt = parse_session_and_prompt(rest)
            if not session_name:
                session_name = self.current_session_for_user(str(message.author.id), str(channel.id))
            try:
                session_name = normalize_session(session_name)
            except ValueError as exc:
                await self.reply_forbidden(channel, str(exc))
                return
            await self.handle_resume(message, repo_name, repo_path, session_name, prompt)
            return
        if cmd == "choose":
            choice, sess = parse_choose(rest)
            if not choice:
                await self.reply_forbidden(channel, "Usage: !c choose [session] resume|replace|cancel")
                return
            if sess:
                try:
                    _ = normalize_session(sess)
                except ValueError as exc:
                    await self.reply_forbidden(channel, str(exc))
                    return
            await self.handle_choose(message, repo_name, repo_path, sess, choice)
            return
        if cmd == "stop":
            session = rest.strip()
            if session:
                try:
                    session = normalize_session(session)
                except ValueError as exc:
                    await self.reply_forbidden(channel, str(exc))
                    return
            await self.handle_stop(channel, session)
            return
        if cmd == "kill":
            session = rest.strip()
            if session:
                try:
                    session = normalize_session(session)
                except ValueError as exc:
                    await self.reply_forbidden(channel, str(exc))
                    return
            await self.handle_kill(channel, session)
            return
        if cmd == "/quit":
            session = rest.strip()
            if session:
                try:
                    session = normalize_session(session)
                except ValueError as exc:
                    await self.reply_forbidden(channel, str(exc))
                    return
            await self.handle_quit(channel, session)
            return
        if cmd == "showrepo":
            await self.handle_showrepo(channel, repo_path)
            return
        if cmd == "showchanges":
            await self.handle_showchanges(channel, repo_path)
            return
        if cmd == "tests":
            await self.handle_tests(channel, repo_path)
            return
        if cmd == "git":
            await self.handle_git(channel, repo_path, rest)
            return
        if cmd == "logs":
            session_name, limit = parse_session_or_limit(rest)
            if limit <= 0:
                limit = 5
            if session_name:
                try:
                    session_name = normalize_session(session_name)
                except ValueError as exc:
                    await self.reply_forbidden(channel, str(exc))
                    return
            await self.handle_logs(channel, session_name, limit)
            return
        if cmd == "ps":
            await self.handle_ps(channel)
            return
        if cmd == "cancel":
            job_id = rest.strip()
            if not job_id:
                await self.reply_forbidden(channel, "Usage: !c cancel <job-id>")
                return
            await self.handle_cancel(channel, job_id)
            return
        if cmd == "rerun":
            await self.handle_rerun(channel)
            return
        if cmd in {"use", "select"}:
            if len(fields) < 2:
                await self.reply_forbidden(channel, "Usage: !c use <session>")
                return
            try:
                session_name = normalize_session(fields[1])
            except ValueError as exc:
                await self.reply_forbidden(channel, str(exc))
                return
            await self.handle_select_session(message, session_name)
            return
        if cmd == "thread":
            session_name, thread_id = parse_session_and_id(rest)
            if not thread_id:
                await self.reply_forbidden(channel, "Usage: !c thread [session] <id>")
                return
            if session_name:
                try:
                    session_name = normalize_session(session_name)
                except ValueError as exc:
                    await self.reply_forbidden(channel, str(exc))
                    return
            await self.handle_thread(channel, session_name, repo_name, repo_path, thread_id)
            return
        if cmd == "model":
            if not rest:
                await self.reply_forbidden(channel, "Usage: !c model [session] <model-id>")
                return
            parts = rest.split()
            session_name = self.current_session_for_user(str(message.author.id), str(channel.id))
            if len(parts) == 1:
                model = parts[0]
            else:
                session_name = parts[0]
                model = rest[len(parts[0]) :].strip()
            try:
                session_name = normalize_session(session_name)
            except ValueError as exc:
                await self.reply_forbidden(channel, str(exc))
                return
            if not model:
                await self.reply_forbidden(channel, "Model id required.")
                return
            state = self.state.load()
            if not session_exists(state, str(channel.id), session_name) and count_active_sessions(state, str(channel.id)) >= MAX_SESSIONS_PER_CHANNEL:
                await self.reply_forbidden(channel, f"Session limit reached ({MAX_SESSIONS_PER_CHANNEL}). Stop or reuse an existing session.")
                return
            self.set_session_model(str(channel.id), session_name, repo_name, repo_path, model)
            await self.reply(channel, f"Model for session '{session_name}' set to {model}")
            return
        if cmd == "spec":
            session = rest.strip() or self.current_session_for_user(str(message.author.id), str(channel.id))
            try:
                session = normalize_session(session)
            except ValueError as exc:
                await self.reply_forbidden(channel, str(exc))
                return
            await self.handle_spec(message, repo_name, repo_path, session)
            return
        if cmd == "clonerepo":
            url = rest.strip()
            if not url:
                await self.reply_forbidden(channel, "Usage: !c clonerepo <github-url>")
                return
            try:
                repo_path = pathutil.resolve_repo_path_for_create(self.cfg.codex.code_root, repo_name)
            except Exception as exc:
                await self.reply_forbidden(channel, f"Repo error: {exc}")
                return
            await self.handle_clone_repo(message, repo_name, repo_path, url)
            return
        if cmd == "copyrepo":
            new_name = rest.strip()
            if not new_name:
                await self.reply_forbidden(channel, "Usage: !c copyrepo <new-repo-name>")
                return
            try:
                target_path = pathutil.resolve_repo_path_for_create(self.cfg.codex.code_root, new_name)
            except Exception as exc:
                await self.reply_forbidden(channel, f"Repo error: {exc}")
                return
            await self.handle_copy_repo(message, repo_name, repo_path, new_name, target_path)
            return

        await self.handle_resume(message, repo_name, repo_path, DEFAULT_SESSION, cmdline)

    async def handle_dm_message(self, message: discord.Message) -> None:
        """Handle an incoming DM admin message."""
        await dm_admin_handlers.handle_dm_message(self, message)

    async def handle_start(self, message: discord.Message, repo_name: str, repo_path: str, session: str) -> None:
        """Start a new Codex session for a channel/session."""
        await core_handlers.handle_start(self, message, repo_name, repo_path, session)

    async def handle_resume(self, message: discord.Message, repo_name: str, repo_path: str, session: str, prompt: str) -> None:
        """Resume a Codex session with a prompt."""
        await core_handlers.handle_resume(self, message, repo_name, repo_path, session, prompt)

    async def handle_create_repo(self, message: discord.Message, repo_name: str, repo_path: str) -> None:
        """Create a new repo directory and git init."""
        await core_handlers.handle_create_repo(self, message, repo_name, repo_path)

    async def handle_clone_repo(self, message: discord.Message, repo_name: str, repo_path: str, raw_url: str) -> None:
        """Clone a GitHub repo into code_root for the channel name."""
        await core_handlers.handle_clone_repo(self, message, repo_name, repo_path, raw_url)

    async def handle_copy_repo(
        self,
        message: discord.Message,
        repo_name: str,
        repo_path: str,
        new_name: str,
        target_path: str,
    ) -> None:
        """Copy an existing repo into a new directory without .git."""
        await core_handlers.handle_copy_repo(self, message, repo_name, repo_path, new_name, target_path)

    async def handle_spec(self, message: discord.Message, repo_name: str, repo_path: str, session: str) -> None:
        """Run the spec capture flow via Codex."""
        await core_handlers.handle_spec(self, message, repo_name, repo_path, session)

    async def handle_choose(self, message: discord.Message, repo_name: str, repo_path: str, session: str, choice: str) -> None:
        """Resolve a pending start conflict."""
        await core_handlers.handle_choose(self, message, repo_name, repo_path, session, choice)

    async def handle_stop(self, channel: discord.abc.Messageable, session: str) -> None:
        """Send a stop signal to a running Codex process."""
        await core_handlers.handle_stop(self, channel, session)

    async def handle_kill(self, channel: discord.abc.Messageable, session: str) -> None:
        """Force-kill a running Codex process."""
        await core_handlers.handle_kill(self, channel, session)

    async def handle_quit(self, channel: discord.abc.Messageable, session: str) -> None:
        """Send /quit to the Codex process."""
        await core_handlers.handle_quit(self, channel, session)

    async def handle_showrepo(self, channel: discord.abc.Messageable, repo_path: str) -> None:
        """Show a pruned repo tree for orientation."""
        await repo_handlers.handle_showrepo(self, channel, repo_path)

    async def handle_showchanges(self, channel: discord.abc.Messageable, repo_path: str) -> None:
        """Show git status and diffstat for the repo."""
        await repo_handlers.handle_showchanges(self, channel, repo_path)

    async def handle_tests(self, channel: discord.abc.Messageable, repo_path: str) -> None:
        """Run tests for the repo (pytest -q)."""
        await repo_handlers.handle_tests(self, channel, repo_path)

    async def handle_git(self, channel: discord.abc.Messageable, repo_path: str, rest: str) -> None:
        """Run safe git helper commands."""
        await git_handlers.handle_git(self, channel, repo_path, rest)

    async def handle_logs(self, channel: discord.abc.Messageable, session: str, limit: int) -> None:
        """Show recent audit log entries."""
        try:
            summaries = self.audit.summaries(str(channel.id), session, limit)
        except Exception as exc:
            await self.reply(channel, f"logs error: {exc}")
            return
        if not summaries:
            await self.reply(channel, "No logs yet.")
            return
        lines = []
        for s in summaries:
            lines.append(f"[{s.seq}] channel:{s.channel_id} session:{s.session} thread:{s.thread_id}")
        text = "\n".join(lines)
        for chunk in chunk_text(text, self.cfg.discord.max_discord_message_chars):
            await self.reply(channel, chunk)

    async def handle_ps(self, channel: discord.abc.Messageable) -> None:
        """Show queued/running jobs for the channel."""
        statuses = await self.queue.snapshot(str(channel.id))
        if not statuses:
            await self.reply_forbidden(channel, "No jobs queued or running.")
            return
        lines = []
        for st in statuses:
            lines.append(f"{st.job_id} [{st.status}] session:{st.session or DEFAULT_SESSION} pos:{st.position}")
        await self.reply(channel, "\n".join(lines))

    async def handle_cancel(self, channel: discord.abc.Messageable, job_id: str) -> None:
        """Cancel a queued job by id."""
        ok = await self.queue.cancel(str(channel.id), job_id)
        if ok:
            await self.reply(channel, f"Cancelled {job_id}")
        else:
            await self.reply(channel, "Job not found or already running.")

    async def handle_rerun(self, channel: discord.abc.Messageable) -> None:
        """Re-queue the last job for the channel."""
        record = await self.queue.last_job(str(channel.id))
        if not record:
            await self.reply_forbidden(channel, "No job to rerun.")
            return
        pos, job_id, _ = await self.queue.enqueue(str(channel.id), record.session, record.job)
        await self.reply(channel, f"Re-queued last job (session '{record.session or DEFAULT_SESSION}') as {job_id} (position {pos})")

    async def handle_select_session(self, message: discord.Message, session: str) -> None:
        """Set a sticky session selection for a user."""
        channel_id = str(message.channel.id)
        user_id = str(message.author.id)
        self.sessions.set_sticky(channel_id, user_id, session)
        await self.update_pinned_status(message.channel, user_id, session)
        await self.reply(message.channel, f"Current session set to '{session}' for you in this channel.")

    async def handle_thread(self, channel: discord.abc.Messageable, session: str, repo_name: str, repo_path: str, thread_id: str) -> None:
        """Attach a thread id to a session."""
        if not session:
            session = DEFAULT_SESSION
        self.update_state(str(channel.id), session, repo_name, repo_path, thread_id, self.session_model(str(channel.id), session))
        await self.reply(channel, f"Thread for session '{session}' set to {thread_id}")

    async def handle_stats(self, channel: discord.abc.Messageable, session: str) -> None:
        """Show token usage stats for a session."""
        stats = self.get_usage(str(channel.id), session)
        if not stats:
            await self.reply(channel, "No usage recorded yet for this session.")
            return
        await self.reply(channel, f"Usage for session '{session}': input {stats.input_tokens}, output {stats.output_tokens}, total {stats.total_tokens}")

    async def handle_peek(self, channel: discord.abc.Messageable, session: str) -> None:
        """Show running status and last output time."""
        channel_id = str(channel.id)
        active = await self.get_active(channel_id, session)
        last = self.get_activity(channel_id, session)
        if active is None:
            if last:
                await self.reply(channel, f"No active job. Last output for session '{session}' at {last}")
                return
            await self.reply(channel, "No active job.")
            return
        if last:
            await self.reply(channel, f"Codex is running for session '{session}'. Last output at {last}")
            return
        await self.reply(channel, f"Codex is running for session '{session}'.")

    async def send_status(self, channel: discord.abc.Messageable, repo_name: str, repo_path: str) -> None:
        """Send status summary for the channel and sessions."""
        state = self.state.load()
        ch = state.channels.get(str(channel.id))
        if ch and ch.sessions:
            lines = [f"Repo: {repo_name}", f"Path: {repo_path}", f"Sessions ({len(ch.sessions)}/{MAX_SESSIONS_PER_CHANNEL}):"]
            for name, sess in ch.sessions.items():
                active = " (active)" if await self.get_active(str(channel.id), name) is not None else ""
                model = sess.model or self.cfg.codex.model
                model_info = f" model {model}" if model else ""
                lines.append(f"- {name}: thread {sess.thread_id}{active}{model_info} last {sess.last_used_at}")
            current = self.current_session_for_user("", str(channel.id))
            if current:
                lines.append(f"Current selection: {current}")
            await self.reply(channel, "\n".join(lines))
            return
        await self.reply(channel, f"Repo: {repo_name}\nPath: {repo_path}\nNo session attached.")

    async def send_help(self, channel: discord.abc.Messageable) -> None:
        """Send help text for supported commands."""
        text = (
            "Commands:\n"
            "General:\n"
            "help — show this help\n"
            "status — show repo path and sessions\n"
            "stats [session] — show usage totals\n"
            "peek [session] — show active status and last output time\n"
            "config — show effective config\n"
            "\n"
            "Sessions:\n"
            "start [session] — start a new Codex session\n"
            "resume [session] <prompt> — resume with prompt\n"
            "choose [session] resume|replace|cancel — resolve start conflict\n"
            "use/select <session> — set your sticky session\n"
            "model [session] <id> — set session model\n"
            "thread [session] <id> — set thread id\n"
            "\n"
            "Repo bootstrap:\n"
            "createrepo — create repo in code_root and git init\n"
            "clonerepo <url> — clone GitHub repo into code_root\n"
            "copyrepo <newname> — copy repo without .git, init git, continue in new channel\n"
            "spec [session] — capture spec into instructions/spec.md and tasks\n"
            "\n"
            "Run control:\n"
            "stop [session] — send ESC then SIGINT\n"
            "kill [session] — force kill running process\n"
            "/quit [session] — send /quit to Codex\n"
            "\n"
            "Repo helpers:\n"
            "showrepo — list repo tree\n"
            "showchanges — git status + diffstat\n"
            "tests — run pytest -q\n"
            "git <status|log|branches|show|diff|pull|commit|push|merge> — git helpers\n"
            "\n"
            "Queue:\n"
            "logs [session] [n] — show recent audit entries\n"
            "ps — list queued/running jobs\n"
            "cancel <job-id> — cancel queued job\n"
            "rerun — requeue last job\n"
        )
        await self.reply(channel, text)

    def config_text(self) -> str:
        """Render a concise config summary."""
        cfg = self.cfg
        return (
            f"code_root: {cfg.codex.code_root}\n"
            f"sandbox: {cfg.codex.sandbox}\n"
            f"model: {cfg.codex.model}\n"
            f"prefix: {cfg.discord.prefix}\n"
            f"allow_plain_prompts: {cfg.discord.allow_plain_prompts}\n"
            f"channel regex: {cfg.discord.channel_name_regex}\n"
            f"allowed_user_ids: {len(cfg.discord.allowed_user_ids)}\n"
            f"dm_admin_enabled: {cfg.discord.dm_admin_enabled}\n"
            f"dm_admin_user_ids: {len(cfg.discord.dm_admin_user_ids)}"
        )

    async def run_codex(
        self,
        message: discord.Message,
        repo_name: str,
        repo_path: str,
        session: str,
        model: str,
        args: list[str],
    ) -> None:
        """Run Codex with streaming callbacks and audit logging."""
        channel_id = str(message.channel.id)
        meta = {
            "repo_name": repo_name,
            "repo_path": repo_path,
            "args": args,
            "model": model,
            "timestamp": utc_now_iso(),
            "channel": channel_id,
        }
        entry = self.audit_start(channel_id, session or DEFAULT_SESSION, "pending", meta)
        async with self.typing_context(message.channel):
            try:
                proc = await self.runner.run(
                    Options(
                        repo_path=repo_path,
                        args=args,
                        env=self.cfg.codex.env,
                        on_jsonl=lambda line: self.on_jsonl(message.channel, channel_id, session, entry, line),
                        on_thread=lambda tid: self.on_thread(channel_id, session, repo_name, repo_path, model, entry, tid),
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

    async def on_jsonl(self, channel: discord.abc.Messageable, channel_id: str, session: str, entry: Optional[Entry], line: str) -> None:
        """Handle a JSONL line from Codex and relay output."""
        self.append_audit_codex(entry, line)
        evt = parse_event(line)
        if not evt:
            text = strip_control_codes(line).strip()
            if text:
                for chunk in chunk_text(text, self.cfg.discord.max_discord_message_chars):
                    self.append_audit_discord(entry, chunk)
                    await self.reply(channel, chunk)
            return
        self.update_usage(channel_id, session, evt)
        self.update_activity(channel_id, session)
        for msg in display_texts(evt):
            text = strip_control_codes(msg)
            if needs_user_input(text):
                text = f"Codex asks: {text}"
            for chunk in chunk_text(text, self.cfg.discord.max_discord_message_chars):
                self.append_audit_discord(entry, chunk)
                await self.reply(channel, chunk)

    async def on_thread(
        self,
        channel_id: str,
        session: str,
        repo_name: str,
        repo_path: str,
        model: str,
        entry: Optional[Entry],
        thread_id: str,
    ) -> None:
        """Handle thread id updates from Codex."""
        if entry:
            entry.thread_id = thread_id
            entry.session = session or DEFAULT_SESSION
        self.update_state(channel_id, session, repo_name, repo_path, thread_id, model)

    async def on_exit(self, channel_id: str, session: str, repo_name: str, err: Optional[BaseException], rc: int) -> None:
        """Handle Codex process exit events."""
        await self.clear_active(channel_id, session)
        if err:
            self.logger.error("codex.exit", extra={"channel_id": channel_id, "repo": repo_name, "session": session, "error": str(err)})
            return
        self.logger.info("codex.exit", extra={"channel_id": channel_id, "repo": repo_name, "session": session, "code": rc})

    async def reply(self, channel: discord.abc.Messageable, content: str) -> None:
        """Send a reply to a channel, chunking as needed."""
        content = strip_control_codes(content)
        for chunk in chunk_text(content, self.cfg.discord.max_discord_message_chars):
            await channel.send(chunk)
            if await self.has_active(str(channel.id)):
                if hasattr(channel, "trigger_typing"):
                    try:
                        await channel.trigger_typing()
                    except Exception:
                        pass

    async def reply_forbidden(self, channel: discord.abc.Messageable, detail: str) -> None:
        """Send a standardized forbidden/invalid response."""
        await channel.send(forbidden_message(detail))

    def _dm_admin_allowed(self, user_id: str) -> bool:
        if self.cfg.discord.dm_admin_user_ids:
            return user_id in self.cfg.discord.dm_admin_user_ids
        return user_id in self.cfg.discord.allowed_user_ids

    @asynccontextmanager
    async def typing_context(self, channel: discord.abc.Messageable):
        """Provide a typing indicator context with fallback."""
        if hasattr(channel, "typing"):
            async with channel.typing():
                yield
            return
        if not hasattr(channel, "trigger_typing"):
            yield
            return
        stop = asyncio.Event()

        async def _loop() -> None:
            while not stop.is_set():
                try:
                    await channel.trigger_typing()
                except Exception:
                    pass
                try:
                    await asyncio.wait_for(stop.wait(), timeout=8.0)
                except asyncio.TimeoutError:
                    continue

        task = asyncio.create_task(_loop())
        try:
            yield
        finally:
            stop.set()
            task.cancel()

    async def update_pinned_status(self, channel: discord.abc.Messageable, user_id: str, session: str) -> None:
        """Update or pin the current session status message."""
        if not isinstance(channel, discord.TextChannel):
            return
        text = f"User {user_id} current session: {session or DEFAULT_SESSION}"
        msg_id = self._pins.get(str(channel.id))
        if msg_id:
            try:
                msg = await channel.fetch_message(msg_id)
                await msg.edit(content=text)
                return
            except Exception:
                self._pins.pop(str(channel.id), None)
        try:
            msg = await channel.send(text)
        except Exception:
            return
        try:
            await msg.pin()
        except Exception:
            pass
        self._pins[str(channel.id)] = msg.id

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
                    statuses = await self.queue.snapshot(channel_id)
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

    def append_audit_discord(self, entry: Optional[Entry], msg: str) -> None:
        """Append a Discord message to the audit log."""
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

    def update_state(self, channel_id: str, session: str, repo_name: str, repo_path: str, thread_id: str, model: str) -> None:
        """Update persistent state for a session."""
        self.sessions.update_state(channel_id, session, repo_name, repo_path, thread_id, model)

    def session_model(self, channel_id: str, session: str) -> str:
        """Return model override for a session or fallback to default."""
        return self.sessions.session_model(channel_id, session)

    def set_session_model(self, channel_id: str, session: str, repo_name: str, repo_path: str, model: str) -> None:
        """Set a model override for a session."""
        self.sessions.set_session_model(channel_id, session, repo_name, repo_path, model)

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
        self.sessions.update_activity(channel_id, session or DEFAULT_SESSION)

    def get_activity(self, channel_id: str, session: str) -> Optional[str]:
        """Return last output time for a session."""
        return self.sessions.get_activity(channel_id, session or DEFAULT_SESSION)

    async def set_active(self, channel_id: str, session: str, proc: Any) -> None:
        """Track a running Codex process for a session."""
        await self.sessions.set_active(channel_id, session or DEFAULT_SESSION, proc)

    async def clear_active(self, channel_id: str, session: str) -> None:
        """Clear the running process for a session."""
        await self.sessions.clear_active(channel_id, session or DEFAULT_SESSION)

    async def get_active(self, channel_id: str, session: str) -> Optional[Any]:
        """Return the running process for a session, if any."""
        return await self.sessions.get_active(channel_id, session or DEFAULT_SESSION)

    async def has_active(self, channel_id: str) -> bool:
        """Return True if any session is active in a channel."""
        return await self.sessions.has_active(channel_id)

    async def consume_pending(self, channel_id: str, session: str) -> Optional[PendingConflict]:
        """Consume a pending conflict if present and not expired."""
        return await self.sessions.consume_pending(channel_id, session)

    def current_session_for_user(self, user_id: str, channel_id: str) -> str:
        """Return sticky session selection for a user or default."""
        return self.sessions.current_session_for_user(user_id, channel_id)
