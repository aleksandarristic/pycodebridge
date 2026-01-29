import asyncio
import os
import re
import shlex
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

import discord

from . import config as cfgmod
from .audit import Entry, Logger as AuditLogger
from .codex import Event, Options, Runner, display_texts, parse_event
from .queue import Manager
from .state import Store, utc_now_iso
from .util import path as pathutil
from .util.ansi import strip_control_codes
from .util.chunk import chunk_text
from .util.prompt import needs_user_input

FORBIDDEN_PREFIX = "I'm sorry, Dave. I'm afraid I can't do that."
DEFAULT_SESSION = "default"
MAX_SESSIONS_PER_CHANNEL = 3
SESSION_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

HELPER_TIMEOUT = 30.0
TESTS_TIMEOUT = 120.0
HELPER_OUTPUT_LIMIT = 128 * 1024


@dataclass
class PendingConflict:
    repo_name: str
    session: str
    thread_id: str
    user_id: str
    expires_at: float


@dataclass
class UsageStats:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


class Router:
    def __init__(self, cfg: cfgmod.Config, state: Store, audit: AuditLogger, runner: Runner, queue: Manager, logger):
        self.cfg = cfg
        self.state = state
        self.audit = audit
        self.runner = runner
        self.queue = queue
        self.logger = logger
        self._pins: Dict[str, int] = {}
        self._active: Dict[str, Dict[str, Any]] = {}
        self._activity: Dict[str, Dict[str, float]] = {}
        self._usage: Dict[str, Dict[str, UsageStats]] = {}
        self._pending: Dict[str, PendingConflict] = {}
        self._lock = asyncio.Lock()

    async def handle_message(self, client: discord.Client, message: discord.Message) -> None:
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
            await self.handle_dm_message(message)
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
            await self.reply_forbidden(channel, "createrepo not implemented yet.")
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
            await self.reply_forbidden(channel, "spec not implemented yet.")
            return
        if cmd == "clonerepo":
            await self.reply_forbidden(channel, "clonerepo not implemented yet.")
            return
        if cmd == "copyrepo":
            await self.reply_forbidden(channel, "copyrepo not implemented yet.")
            return

        await self.handle_resume(message, repo_name, repo_path, DEFAULT_SESSION, cmdline)

    async def handle_dm_message(self, message: discord.Message) -> None:
        content = (message.content or "").strip()
        if not content.startswith(self.cfg.discord.prefix or "!c"):
            return
        cmdline = content[len(self.cfg.discord.prefix or "!c") :].strip()
        if not cmdline:
            return
        fields = cmdline.split()
        cmd = fields[0].lower()
        rest = cmdline[len(fields[0]) :].strip()

        entry = self.dm_audit_start(message, cmd, rest)

        async def send(text: str) -> None:
            await self.dm_reply(message.channel, entry, text)

        async def send_forbidden(detail: str) -> None:
            await self.dm_reply(message.channel, entry, forbidden_message(detail))

        if cmd == "help":
            await send(self.dm_help_text())
            return
        if cmd == "repos":
            msg = await self.dm_list_repos()
            await send(msg)
            return
        if cmd == "sessions":
            msg = await self.dm_list_sessions()
            await send(msg)
            return
        if cmd == "status":
            await send(await self.dm_status())
            return
        if cmd == "config":
            await send(self.config_text())
            return
        if cmd in {"createrepo", "clonerepo", "copyrepo", "deleterepo", "delete", "renamerepo", "rename"}:
            await send_forbidden("DM repo commands not implemented yet.")
            return

        await send_forbidden("Unknown DM command. Try !c help.")

    async def handle_start(self, message: discord.Message, repo_name: str, repo_path: str, session: str) -> None:
        channel_id = str(message.channel.id)
        session = normalize_session(session)
        state = self.state.load()
        if count_active_sessions(state, channel_id) >= MAX_SESSIONS_PER_CHANNEL:
            if not session_exists(state, channel_id, session):
                await self.reply_forbidden(message.channel, f"Session limit reached ({MAX_SESSIONS_PER_CHANNEL}). Stop or reuse an existing session.")
                return
        thread_id = existing_thread(state, channel_id, session)
        if thread_id:
            async with self._lock:
                key = pending_key(channel_id, session)
                self._pending[key] = PendingConflict(
                    repo_name=repo_name,
                    session=session,
                    thread_id=thread_id,
                    user_id=str(message.author.id),
                    expires_at=time.time() + self.cfg.state.conflict_ttl_seconds,
                )
            await self.reply(message.channel, f"Session '{session}' already exists for this channel.\nChoose one:\n!c choose resume\n!c choose replace\n!c choose cancel")
            return

        model = self.session_model(channel_id, session)
        args = self.runner.build_start_args(repo_path, self.cfg.codex.start_prompt.replace("{{REPO_NAME}}", repo_name), model)

        async def job() -> None:
            await self.run_codex(message, repo_name, repo_path, session, model, args)

        pos, job_id, _ = await self.queue.enqueue(channel_id, session, job)
        self.logger.info("enqueue.start", extra={"channel_id": channel_id, "repo": repo_name, "session": session, "job": job_id, "pos": pos})

    async def handle_resume(self, message: discord.Message, repo_name: str, repo_path: str, session: str, prompt: str) -> None:
        channel_id = str(message.channel.id)
        session = normalize_session(session)
        state = self.state.load()
        thread_id = existing_thread(state, channel_id, session)
        model = self.session_model(channel_id, session)
        if thread_id:
            args = self.runner.build_resume_args(repo_path, thread_id, prompt, model)
        else:
            args = self.runner.build_resume_last_args(repo_path, prompt, model)

        async def job() -> None:
            await self.run_codex(message, repo_name, repo_path, session, model, args)

        pos, job_id, _ = await self.queue.enqueue(channel_id, session, job)
        self.logger.info("enqueue.resume", extra={"channel_id": channel_id, "repo": repo_name, "session": session, "job": job_id, "pos": pos})

    async def handle_choose(self, message: discord.Message, repo_name: str, repo_path: str, session: str, choice: str) -> None:
        channel_id = str(message.channel.id)
        conflict = await self.consume_pending(channel_id, session)
        if not conflict:
            await self.reply(message.channel, "No pending conflict.")
            return
        choice = choice.lower()
        if choice == "resume":
            await self.reply(message.channel, f"Resuming existing session '{conflict.session}'...")
            await self.handle_resume(message, repo_name, repo_path, conflict.session, "Resumed.")
            return
        if choice == "replace":
            await self.reply(message.channel, f"Replacing session '{conflict.session}' with new start...")
            await self.handle_start(message, repo_name, repo_path, conflict.session)
            return
        if choice == "cancel":
            await self.reply(message.channel, "Cancelled.")
            return
        await self.reply(message.channel, "Unknown choice. Use resume|replace|cancel.")

    async def handle_stop(self, channel: discord.abc.Messageable, session: str) -> None:
        channel_id = str(channel.id)
        proc = await self.get_active(channel_id, session)
        if proc is not None:
            await proc.stop()
            await asyncio.sleep(0.5)
            await proc.interrupt()
            await self.reply(channel, f"Sent stop (ESC then SIGINT) to session '{session or DEFAULT_SESSION}'.")
            return
        await self.reply(channel, "No running Codex process.")

    async def handle_kill(self, channel: discord.abc.Messageable, session: str) -> None:
        channel_id = str(channel.id)
        proc = await self.get_active(channel_id, session)
        if proc is not None:
            await proc.kill()
            await self.reply(channel, f"Sent kill to session '{session or DEFAULT_SESSION}'.")
            return
        await self.reply_forbidden(channel, "No running Codex process.")

    async def handle_quit(self, channel: discord.abc.Messageable, session: str) -> None:
        channel_id = str(channel.id)
        proc = await self.get_active(channel_id, session)
        if proc is not None:
            await proc.write("/quit\n")
            await self.reply(channel, f"Sent /quit to session '{session or DEFAULT_SESSION}'.")
            return
        await self.reply_forbidden(channel, "No running Codex process.")

    async def handle_showrepo(self, channel: discord.abc.Messageable, repo_path: str) -> None:
        text = build_tree(repo_path, max_depth=3)
        text = trim_output(text, 300, 6000)
        for chunk in chunk_text(text, self.cfg.discord.max_discord_message_chars):
            await self.reply(channel, chunk)

    async def handle_showchanges(self, channel: discord.abc.Messageable, repo_path: str) -> None:
        out, err = await run_limited_command(repo_path, ["git", "status", "--short", "--branch"])
        out2, err2 = await run_limited_command(repo_path, ["git", "diff", "--stat"])
        text = strip_control_codes(out + "\n" + out2)
        text = trim_output(text, 200, 4000)
        if err or err2:
            text = f"showchanges error: {err or err2}\n{text}"
        text = "```diff\n" + text + "\n```"
        for chunk in chunk_text(text, self.cfg.discord.max_discord_message_chars):
            await self.reply(channel, chunk)

    async def handle_tests(self, channel: discord.abc.Messageable, repo_path: str) -> None:
        out, err = await run_limited_command(repo_path, ["pytest", "-q"], timeout=TESTS_TIMEOUT)
        text = strip_control_codes(out)
        text = trim_output(text, 200, 6000)
        if err:
            reason = "Tests failed"
            if isinstance(err, asyncio.TimeoutError):
                reason = "Tests timed out"
            text = f"{reason}: {err}\n{text}"
        for chunk in chunk_text(text, self.cfg.discord.max_discord_message_chars):
            await self.reply(channel, chunk)

    async def handle_git(self, channel: discord.abc.Messageable, repo_path: str, rest: str) -> None:
        fields = shlex.split(rest) if rest else []
        if not fields:
            await self.reply(channel, "Usage: !c git <status|log|branches|show|diff|pull|commit|push|merge> [args]")
            return
        sub = fields[0].lower()
        args = fields[1:]
        bad = find_unsafe_git_flag(args)
        if bad:
            await self.reply_forbidden(channel, f"Forbidden git flag: {bad}")
            return
        git_args: list[str] = []
        wrap_diff = False
        if sub == "status":
            git_args = ["status", "--short", "--branch"]
        elif sub == "log":
            n = parse_log_count(args)
            git_args = ["log", f"-n{n}", "--oneline"]
        elif sub == "branches":
            git_args = ["branch", "--all", "--list"]
        elif sub == "show":
            if not args:
                await self.reply(channel, "Usage: !c git show <rev>")
                return
            git_args = ["show", args[0]] + args[1:]
        elif sub == "diff":
            if not args:
                await self.reply_forbidden(channel, "Usage: !c git diff <args>")
                return
            git_args = ["diff"] + args
            wrap_diff = True
        elif sub == "pull":
            if has_forbidden_flags(args):
                await self.reply_forbidden(channel, "Forbidden flags detected (--force/-f/--rebase/--squash).")
                return
            git_args = ["pull", "--no-rebase"] + args
        elif sub == "commit":
            if not args:
                await self.reply_forbidden(channel, "Usage: !c git commit <message>")
                return
            msg = " ".join(args)
            git_args = ["commit", "-am", msg]
        elif sub == "push":
            if has_forbidden_flags(args):
                await self.reply_forbidden(channel, "Forbidden flags detected (--force/-f/--rebase/--squash).")
                return
            git_args = ["push"] + args
        elif sub == "merge":
            if not args:
                await self.reply_forbidden(channel, "Usage: !c git merge <branch>")
                return
            if has_forbidden_flags(args):
                await self.reply_forbidden(channel, "Forbidden flags detected (--force/-f/--rebase/--squash).")
                return
            git_args = ["merge"] + args
        else:
            await self.reply_forbidden(channel, "Unknown git subcommand.")
            return

        out, err = await run_limited_command(repo_path, ["git"] + git_args)
        text = strip_control_codes(out)
        text = trim_output(text, 200, 4000)
        if wrap_diff:
            text = "```diff\n" + text + "\n```"
        if err:
            text = f"git {sub} error: {err}\n{text}"
        for chunk in chunk_text(text, self.cfg.discord.max_discord_message_chars):
            await self.reply(channel, chunk)

    async def handle_logs(self, channel: discord.abc.Messageable, session: str, limit: int) -> None:
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
        statuses = await self.queue.snapshot(str(channel.id))
        if not statuses:
            await self.reply_forbidden(channel, "No jobs queued or running.")
            return
        lines = []
        for st in statuses:
            lines.append(f"{st.job_id} [{st.status}] session:{st.session or DEFAULT_SESSION} pos:{st.position}")
        await self.reply(channel, "\n".join(lines))

    async def handle_cancel(self, channel: discord.abc.Messageable, job_id: str) -> None:
        ok = await self.queue.cancel(str(channel.id), job_id)
        if ok:
            await self.reply(channel, f"Cancelled {job_id}")
        else:
            await self.reply(channel, "Job not found or already running.")

    async def handle_rerun(self, channel: discord.abc.Messageable) -> None:
        record = await self.queue.last_job(str(channel.id))
        if not record:
            await self.reply_forbidden(channel, "No job to rerun.")
            return
        pos, job_id, _ = await self.queue.enqueue(str(channel.id), record.session, record.job)
        await self.reply(channel, f"Re-queued last job (session '{record.session or DEFAULT_SESSION}') as {job_id} (position {pos})")

    async def handle_select_session(self, message: discord.Message, session: str) -> None:
        channel_id = str(message.channel.id)
        user_id = str(message.author.id)
        self.state.update(lambda fs: set_sticky(fs, channel_id, user_id, session))
        await self.update_pinned_status(message.channel, user_id, session)
        await self.reply(message.channel, f"Current session set to '{session}' for you in this channel.")

    async def handle_thread(self, channel: discord.abc.Messageable, session: str, repo_name: str, repo_path: str, thread_id: str) -> None:
        if not session:
            session = DEFAULT_SESSION
        self.update_state(str(channel.id), session, repo_name, repo_path, thread_id, self.session_model(str(channel.id), session))
        await self.reply(channel, f"Thread for session '{session}' set to {thread_id}")

    async def handle_stats(self, channel: discord.abc.Messageable, session: str) -> None:
        stats = self.get_usage(str(channel.id), session)
        if not stats:
            await self.reply(channel, "No usage recorded yet for this session.")
            return
        await self.reply(channel, f"Usage for session '{session}': input {stats.input_tokens}, output {stats.output_tokens}, total {stats.total_tokens}")

    async def handle_peek(self, channel: discord.abc.Messageable, session: str) -> None:
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
        stop_typing = self.start_typing(message.channel)
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
            stop_typing()
            self.close_audit(entry)
            raise exc

        await self.set_active(channel_id, session, proc)
        try:
            rc = await proc.wait()
            if rc != 0:
                self.logger.warning("codex.exit", extra={"channel_id": channel_id, "repo": repo_name, "session": session, "code": rc})
        finally:
            stop_typing()
            await self.clear_active(channel_id, session)
            self.close_audit(entry)

    async def on_jsonl(self, channel: discord.abc.Messageable, channel_id: str, session: str, entry: Optional[Entry], line: str) -> None:
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
        if entry:
            entry.thread_id = thread_id
            entry.session = session or DEFAULT_SESSION
        self.update_state(channel_id, session, repo_name, repo_path, thread_id, model)

    async def on_exit(self, channel_id: str, session: str, repo_name: str, err: Optional[BaseException], rc: int) -> None:
        await self.clear_active(channel_id, session)
        if err:
            self.logger.error("codex.exit", extra={"channel_id": channel_id, "repo": repo_name, "session": session, "error": str(err)})
            return
        self.logger.info("codex.exit", extra={"channel_id": channel_id, "repo": repo_name, "session": session, "code": rc})

    async def reply(self, channel: discord.abc.Messageable, content: str) -> None:
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
        await channel.send(forbidden_message(detail))

    def _dm_admin_allowed(self, user_id: str) -> bool:
        if self.cfg.discord.dm_admin_user_ids:
            return user_id in self.cfg.discord.dm_admin_user_ids
        return user_id in self.cfg.discord.allowed_user_ids

    def start_typing(self, channel: discord.abc.Messageable) -> Callable[[], None]:
        if not hasattr(channel, "trigger_typing"):
            return lambda: None
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

        def _stop() -> None:
            if not stop.is_set():
                stop.set()
            task.cancel()

        return _stop

    async def update_pinned_status(self, channel: discord.abc.Messageable, user_id: str, session: str) -> None:
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

    def dm_help_text(self) -> str:
        return (
            "DM Admin:\n"
            "help — show this help\n"
            "repos — list repos under code_root\n"
            "sessions — list sessions across channels\n"
            "status — show queues and running jobs\n"
            "config — show effective config\n"
            "createrepo <name> — create repo\n"
            "clonerepo <name> <url> — clone repo\n"
            "copyrepo <from> <to> — copy repo\n"
            "deleterepo <name> — delete repo\n"
            "renamerepo <from> <to> — rename repo\n"
        )

    async def dm_reply(self, channel: discord.abc.Messageable, entry: Optional[Entry], msg: str) -> None:
        self.append_audit_discord(entry, msg)
        await channel.send(msg)

    def dm_audit_start(self, message: discord.Message, cmd: str, rest: str) -> Optional[Entry]:
        meta = {
            "command": cmd,
            "args": rest,
            "timestamp": utc_now_iso(),
            "channel": f"dm-{message.author.id}",
        }
        return self.audit_start(f"dm-{message.author.id}", "admin", "dm", meta)

    async def dm_list_repos(self) -> str:
        base = self.cfg.codex.code_root
        if not base or not os.path.isdir(base):
            return "code_root does not exist."
        entries = []
        for name in sorted(os.listdir(base)):
            path = os.path.join(base, name)
            if not os.path.isdir(path):
                continue
            try:
                mtime = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(os.path.getmtime(path)))
            except Exception:
                mtime = "unknown"
            entries.append(f"{name} (modified {mtime})")
        return "\n".join(entries) if entries else "No repos found."

    async def dm_list_sessions(self) -> str:
        state = self.state.load()
        lines = []
        for channel_id, ch in state.channels.items():
            for name, sess in ch.sessions.items():
                lines.append(f"channel {channel_id} repo {sess.repo_name} session {name} last {sess.last_used_at}")
        return "\n".join(lines) if lines else "No sessions found."

    async def dm_status(self) -> str:
        snapshots = await self.queue.snapshot_all()
        lines = []
        for channel_id, statuses in snapshots.items():
            for st in statuses:
                lines.append(f"{channel_id}: {st.job_id} [{st.status}] session:{st.session or DEFAULT_SESSION} pos:{st.position}")
        return "\n".join(lines) if lines else "No queued or running jobs."

    def audit_start(self, channel_id: str, session: str, thread_id: str, meta: Any) -> Optional[Entry]:
        if not self.audit:
            return None
        try:
            return self.audit.start(channel_id, session, thread_id, meta)
        except Exception as exc:
            self.logger.error("audit.start_failed", extra={"channel_id": channel_id, "session": session, "error": str(exc)})
            return None

    def append_audit_codex(self, entry: Optional[Entry], line: str) -> None:
        if entry:
            try:
                entry.append_codex_line(line)
            except Exception:
                pass

    def append_audit_discord(self, entry: Optional[Entry], msg: str) -> None:
        if entry:
            try:
                entry.append_discord_out(msg)
            except Exception:
                pass

    def append_audit_stderr(self, entry: Optional[Entry], msg: str) -> None:
        if entry:
            try:
                entry.append_stderr(msg)
            except Exception:
                pass

    def close_audit(self, entry: Optional[Entry]) -> None:
        if entry:
            try:
                entry.close()
            except Exception:
                pass

    def update_state(self, channel_id: str, session: str, repo_name: str, repo_path: str, thread_id: str, model: str) -> None:
        session = session or DEFAULT_SESSION

        def mutator(fs):
            ch = fs.channels.get(channel_id)
            if ch is None:
                from .state import ChannelState

                ch = ChannelState()
                fs.channels[channel_id] = ch
            sess = ch.sessions.get(session)
            if sess is None:
                from .state import SessionState

                sess = SessionState(repo_name=repo_name, repo_path=repo_path, thread_id=thread_id)
            if not sess.created_at:
                sess.created_at = utc_now_iso()
            sess.repo_name = repo_name
            sess.repo_path = repo_path
            sess.thread_id = thread_id
            if model:
                sess.model = model
            elif not sess.model and self.cfg.codex.model:
                sess.model = self.cfg.codex.model
            sess.last_used_at = utc_now_iso()
            ch.sessions[session] = sess
            fs.channels[channel_id] = ch

        self.state.update(mutator)

    def session_model(self, channel_id: str, session: str) -> str:
        state = self.state.load()
        ch = state.channels.get(channel_id)
        if ch:
            sess = ch.sessions.get(session or DEFAULT_SESSION)
            if sess and sess.model:
                return sess.model
        return self.cfg.codex.model

    def set_session_model(self, channel_id: str, session: str, repo_name: str, repo_path: str, model: str) -> None:
        self.update_state(channel_id, session, repo_name, repo_path, existing_thread(self.state.load(), channel_id, session), model)

    def update_usage(self, channel_id: str, session: str, evt: Event) -> None:
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
        return self._usage.get(channel_id, {}).get(session)

    def update_activity(self, channel_id: str, session: str) -> None:
        if channel_id not in self._activity:
            self._activity[channel_id] = {}
        self._activity[channel_id][session or DEFAULT_SESSION] = time.time()

    def get_activity(self, channel_id: str, session: str) -> Optional[str]:
        ts = self._activity.get(channel_id, {}).get(session or DEFAULT_SESSION)
        if not ts:
            return None
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))

    async def set_active(self, channel_id: str, session: str, proc: Any) -> None:
        async with self._lock:
            if channel_id not in self._active:
                self._active[channel_id] = {}
            self._active[channel_id][session or DEFAULT_SESSION] = proc

    async def clear_active(self, channel_id: str, session: str) -> None:
        async with self._lock:
            if channel_id in self._active:
                self._active[channel_id].pop(session or DEFAULT_SESSION, None)

    async def get_active(self, channel_id: str, session: str) -> Optional[Any]:
        async with self._lock:
            return self._active.get(channel_id, {}).get(session or DEFAULT_SESSION)

    async def has_active(self, channel_id: str) -> bool:
        async with self._lock:
            if channel_id in self._active:
                return any(self._active[channel_id].values())
        return False

    async def consume_pending(self, channel_id: str, session: str) -> Optional[PendingConflict]:
        async with self._lock:
            if session:
                key = pending_key(channel_id, session)
                conflict = self._pending.pop(key, None)
            else:
                conflict = None
                for key in list(self._pending.keys()):
                    if key.startswith(f"{channel_id}:"):
                        conflict = self._pending.pop(key, None)
                        break
        if not conflict:
            return None
        if conflict.expires_at < time.time():
            return None
        return conflict

    def current_session_for_user(self, user_id: str, channel_id: str) -> str:
        state = self.state.load()
        ch = state.channels.get(channel_id)
        if ch and user_id:
            sess = ch.sticky.get(user_id)
            if sess:
                return sess
        return DEFAULT_SESSION

def forbidden_message(detail: str) -> str:
    return f"{FORBIDDEN_PREFIX}\n```text\n{detail}\n```"


def normalize_session(name: str) -> str:
    if not name:
        return DEFAULT_SESSION
    if not SESSION_RE.match(name):
        raise ValueError("Invalid session name. Use 1-64 characters: letters, numbers, . _ -")
    return name


def pending_key(channel_id: str, session: str) -> str:
    return f"{channel_id}:{session or DEFAULT_SESSION}"


def parse_session_and_prompt(rest: str) -> Tuple[str, str]:
    rest = rest.strip()
    if not rest:
        return DEFAULT_SESSION, ""
    fields = rest.split()
    session = fields[0]
    prompt = rest[len(session) :].strip()
    return session, prompt


def parse_choose(rest: str) -> Tuple[str, str]:
    parts = rest.split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    if len(parts) >= 2 and parts[1] in {"resume", "replace", "cancel"}:
        return parts[1], parts[0]
    return parts[0], ""


def parse_session_or_limit(rest: str) -> Tuple[str, int]:
    rest = rest.strip()
    if not rest:
        return "", 0
    parts = rest.split()
    if not parts:
        return "", 0
    try:
        return "", int(parts[0])
    except ValueError:
        session = parts[0]
        if len(parts) > 1:
            try:
                return session, int(parts[1])
            except ValueError:
                return session, 0
        return session, 0


def parse_session_and_id(rest: str) -> Tuple[str, str]:
    rest = rest.strip()
    if not rest:
        return "", ""
    parts = rest.split()
    if len(parts) == 1:
        return "", parts[0]
    return parts[0], parts[1]


def parse_log_count(args: list[str]) -> int:
    n = 5
    if args:
        try:
            n = int(args[0])
        except ValueError:
            n = 5
    if n <= 0:
        n = 5
    if n > 50:
        n = 50
    return n


def has_forbidden_flags(args: list[str]) -> bool:
    for a in args:
        if a in {"-f", "--force", "--force-with-lease", "--rebase", "--squash"}:
            return True
    return False


def find_unsafe_git_flag(args: list[str]) -> Optional[str]:
    for a in args:
        flag = a
        if flag.startswith("--") and "=" in flag:
            flag = flag.split("=", 1)[0]
        if flag.startswith("-C"):
            return "-C"
        if flag in {"--git-dir", "--work-tree", "-c", "--config-env", "--exec-path", "--upload-pack", "--receive-pack", "--upload-archive", "--namespace"}:
            return flag
    return None


def usage_from_event(evt: Event) -> Optional[UsageStats]:
    if not evt.usage:
        return None
    usage = evt.usage or {}
    return UsageStats(
        input_tokens=int(usage.get("input_tokens") or usage.get("inputTokens") or 0),
        output_tokens=int(usage.get("output_tokens") or usage.get("outputTokens") or 0),
        total_tokens=int(usage.get("total_tokens") or usage.get("totalTokens") or 0),
    )


def count_active_sessions(state, channel_id: str) -> int:
    ch = state.channels.get(channel_id)
    if not ch:
        return 0
    return len(ch.sessions)


def session_exists(state, channel_id: str, session: str) -> bool:
    ch = state.channels.get(channel_id)
    if not ch:
        return False
    return session in ch.sessions


def existing_thread(state, channel_id: str, session: str) -> str:
    ch = state.channels.get(channel_id)
    if not ch:
        return ""
    sess = ch.sessions.get(session or DEFAULT_SESSION)
    if not sess:
        return ""
    return sess.thread_id


def set_sticky(fs, channel_id: str, user_id: str, session: str) -> None:
    ch = fs.channels.get(channel_id)
    if ch is None:
        from .state import ChannelState

        ch = ChannelState()
    if ch.sticky is None:
        ch.sticky = {}
    ch.sticky[user_id] = session
    fs.channels[channel_id] = ch


def build_tree(repo_path: str, max_depth: int = 3) -> str:
    lines: list[str] = []
    base = Path(repo_path)
    if not base.exists():
        return "Repo path not found."

    def walk(path: Path, depth: int) -> None:
        if depth > max_depth:
            return
        try:
            entries = sorted(path.iterdir(), key=lambda p: p.name)
        except Exception:
            return
        for entry in entries:
            name = entry.name
            if name.startswith("."):
                continue
            if name in {".git", "node_modules", "vendor"}:
                continue
            rel = entry.relative_to(base)
            lines.append(str(rel))
            if entry.is_dir():
                walk(entry, depth + 1)

    walk(base, 1)
    return "\n".join(lines) if lines else "(empty)"


def trim_output(text: str, max_lines: int, max_bytes: int) -> str:
    lines = text.split("\n")
    if len(lines) > max_lines:
        lines = lines[:max_lines] + ["...(truncated)"]
    joined = "\n".join(lines)
    if len(joined) > max_bytes:
        joined = joined[:max_bytes] + "\n...(truncated)"
    return joined


async def run_limited_command(repo_path: str, args: list[str], timeout: float = HELPER_TIMEOUT) -> Tuple[str, Optional[Exception]]:
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            cwd=repo_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except Exception as exc:
        return "", exc
    stdout_chunks: list[bytes] = []
    stderr_chunks: list[bytes] = []

    async def _read_stream(stream: asyncio.StreamReader, chunks: list[bytes]) -> None:
        size = 0
        while True:
            data = await stream.read(4096)
            if not data:
                break
            chunks.append(data)
            size += len(data)
            if size > HELPER_OUTPUT_LIMIT:
                break

    try:
        await asyncio.wait_for(
            asyncio.gather(_read_stream(proc.stdout, stdout_chunks), _read_stream(proc.stderr, stderr_chunks)),
            timeout=timeout,
        )
        await asyncio.wait_for(proc.wait(), timeout=timeout)
    except Exception as exc:
        if proc.returncode is None:
            proc.kill()
            await proc.wait()
        return b"".join(stdout_chunks + stderr_chunks).decode("utf-8", errors="replace"), exc

    out = b"".join(stdout_chunks + stderr_chunks).decode("utf-8", errors="replace")
    if proc.returncode != 0:
        return out, RuntimeError(f"exit {proc.returncode}")
    return out, None
