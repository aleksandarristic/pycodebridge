"""Core command handlers for sessions and repo bootstrap."""

from __future__ import annotations

import asyncio
import os
import time
from typing import TYPE_CHECKING

import discord

from ..router_helpers import (
    DEFAULT_SESSION,
    HELPER_TIMEOUT,
    MAX_SESSIONS_PER_CHANNEL,
    PendingConflict,
    count_active_sessions,
    copy_dir_excluding_git,
    existing_thread,
    normalize_session,
    parse_github_clone_url,
    pending_key,
    run_limited_command,
    session_exists,
)

if TYPE_CHECKING:
    from ..router import Router


async def handle_start(router: "Router", message: discord.Message, repo_name: str, repo_path: str, session: str) -> None:
    """Start a new Codex session for a channel/session."""
    channel_id = str(message.channel.id)
    session = normalize_session(session)
    state = router.state.load()
    if count_active_sessions(state, channel_id) >= MAX_SESSIONS_PER_CHANNEL:
        if not session_exists(state, channel_id, session):
            await router.reply_forbidden(message.channel, f"Session limit reached ({MAX_SESSIONS_PER_CHANNEL}). Stop or reuse an existing session.")
            return
    thread_id = existing_thread(state, channel_id, session)
    if thread_id:
        await router.sessions.set_pending_conflict(
            channel_id,
            session,
            PendingConflict(
                repo_name=repo_name,
                session=session,
                thread_id=thread_id,
                user_id=str(message.author.id),
                expires_at=time.time() + router.cfg.state.conflict_ttl_seconds,
            ),
        )
        await router.reply(message.channel, f"Session '{session}' already exists for this channel.\nChoose one:\n!c choose resume\n!c choose replace\n!c choose cancel")
        return

    model = router.session_model(channel_id, session)
    args = router.runner.build_start_args(repo_path, router.cfg.codex.start_prompt.replace("{{REPO_NAME}}", repo_name), model)

    async def job() -> None:
        await router.run_codex(message, repo_name, repo_path, session, model, args)

    pos, job_id, _ = await router.queue.enqueue(channel_id, session, job)
    router.logger.info("enqueue.start", extra={"channel_id": channel_id, "repo": repo_name, "session": session, "job": job_id, "pos": pos})


async def handle_resume(router: "Router", message: discord.Message, repo_name: str, repo_path: str, session: str, prompt: str) -> None:
    """Resume a Codex session with a prompt."""
    channel_id = str(message.channel.id)
    session = normalize_session(session)
    state = router.state.load()
    thread_id = existing_thread(state, channel_id, session)
    model = router.session_model(channel_id, session)
    if thread_id:
        args = router.runner.build_resume_args(repo_path, thread_id, prompt, model)
    else:
        args = router.runner.build_resume_last_args(repo_path, prompt, model)

    async def job() -> None:
        await router.run_codex(message, repo_name, repo_path, session, model, args)

    pos, job_id, _ = await router.queue.enqueue(channel_id, session, job)
    router.logger.info("enqueue.resume", extra={"channel_id": channel_id, "repo": repo_name, "session": session, "job": job_id, "pos": pos})


async def handle_create_repo(router: "Router", message: discord.Message, repo_name: str, repo_path: str) -> None:
    """Create a new repo directory and git init."""
    channel_id = str(message.channel.id)
    if os.path.isdir(repo_path):
        if os.path.isdir(os.path.join(repo_path, ".git")):
            await router.reply_forbidden(message.channel, "Repo already exists; use !c start.")
            router.logger.warning("createrepo.exists", extra={"channel_id": channel_id, "repo": repo_name, "path": repo_path})
            return
        await router.reply_forbidden(message.channel, "Directory already exists and is not a git repo.")
        router.logger.warning("createrepo.exists_non_git", extra={"channel_id": channel_id, "repo": repo_name, "path": repo_path})
        return
    try:
        os.makedirs(repo_path, exist_ok=False)
    except Exception as exc:
        await router.reply_forbidden(message.channel, f"Create repo dir: {exc}")
        router.logger.error("createrepo.mkdir_failed", extra={"channel_id": channel_id, "repo": repo_name, "error": str(exc)})
        return
    _, err = await run_limited_command(repo_path, ["git", "init"])
    if err:
        await router.reply_forbidden(message.channel, f"git init failed: {err}")
        router.logger.error("createrepo.git_init_failed", extra={"channel_id": channel_id, "repo": repo_name, "error": str(err)})
        return
    try:
        router.seed_agents_template(repo_path)
    except Exception as exc:
        await router.reply_forbidden(message.channel, str(exc))
        router.logger.error("createrepo.agents_failed", extra={"channel_id": channel_id, "repo": repo_name, "error": str(exc)})
        return
    await router.reply(message.channel, f"Created repo at {repo_path}")
    router.logger.info("createrepo.ok", extra={"channel_id": channel_id, "repo": repo_name, "path": repo_path})

    session_name = router.current_session_for_user(str(message.author.id), channel_id)
    try:
        session_name = normalize_session(session_name)
    except ValueError as exc:
        await router.reply_forbidden(message.channel, str(exc))
        return
    await router.handle_start(message, repo_name, repo_path, session_name)


async def handle_clone_repo(router: "Router", message: discord.Message, repo_name: str, repo_path: str, raw_url: str) -> None:
    """Clone a GitHub repo into code_root for the channel name."""
    channel_id = str(message.channel.id)
    if os.path.exists(repo_path):
        await router.reply_forbidden(message.channel, "Repo directory already exists.")
        return
    try:
        clone_url = parse_github_clone_url(raw_url)
    except ValueError as exc:
        await router.reply_forbidden(message.channel, str(exc))
        return
    _, err = await run_limited_command(os.path.dirname(repo_path), ["git", "clone", clone_url, repo_path], timeout=HELPER_TIMEOUT * 2)
    if err:
        await router.reply_forbidden(message.channel, f"git clone failed: {err}")
        router.logger.error("clonerepo.failed", extra={"channel_id": channel_id, "repo": repo_name, "url": clone_url, "error": str(err)})
        return
    await router.reply(message.channel, f"Cloned {clone_url} into {repo_path}")
    router.logger.info("clonerepo.ok", extra={"channel_id": channel_id, "repo": repo_name, "url": clone_url, "path": repo_path})


async def handle_copy_repo(
    router: "Router",
    message: discord.Message,
    repo_name: str,
    repo_path: str,
    new_name: str,
    target_path: str,
) -> None:
    """Copy an existing repo into a new directory without .git."""
    channel_id = str(message.channel.id)
    if os.path.exists(target_path):
        await router.reply_forbidden(message.channel, "Target repo directory already exists.")
        return
    try:
        copy_dir_excluding_git(repo_path, target_path)
    except Exception as exc:
        await router.reply_forbidden(message.channel, f"Copy repo failed: {exc}")
        router.logger.error("copyrepo.failed", extra={"channel_id": channel_id, "repo": repo_name, "target": target_path, "error": str(exc)})
        return
    _, err = await run_limited_command(target_path, ["git", "init"])
    if err:
        await router.reply_forbidden(message.channel, f"git init failed: {err}")
        router.logger.error("copyrepo.git_init_failed", extra={"channel_id": channel_id, "repo": repo_name, "target": target_path, "error": str(err)})
        return
    await router.reply(message.channel, f"Copied repo to {target_path}. Continue in #codex-{new_name}")
    router.logger.info("copyrepo.ok", extra={"channel_id": channel_id, "repo": repo_name, "target": target_path})


async def handle_spec(router: "Router", message: discord.Message, repo_name: str, repo_path: str, session: str) -> None:
    """Run the spec capture flow via Codex."""
    channel_id = str(message.channel.id)
    session = normalize_session(session)
    try:
        os.makedirs(os.path.join(repo_path, "instructions"), exist_ok=True)
    except Exception as exc:
        await router.reply_forbidden(message.channel, f"Create instructions dir: {exc}")
        return
    state = router.state.load()
    if count_active_sessions(state, channel_id) >= MAX_SESSIONS_PER_CHANNEL and not session_exists(state, channel_id, session):
        await router.reply_forbidden(message.channel, f"Session limit reached ({MAX_SESSIONS_PER_CHANNEL}). Stop or reuse an existing session.")
        return
    thread_id = existing_thread(state, channel_id, session)
    model = router.session_model(channel_id, session)
    prompt = router.spec_prompt(repo_name)
    if thread_id:
        args = router.runner.build_resume_args(repo_path, thread_id, prompt, model)
    else:
        args = router.runner.build_start_args(repo_path, prompt, model)

    async def job() -> None:
        await router.run_codex(message, repo_name, repo_path, session, model, args)

    pos, job_id, _ = await router.queue.enqueue(channel_id, session, job)
    router.logger.info("enqueue.spec", extra={"channel_id": channel_id, "repo": repo_name, "session": session, "job": job_id, "pos": pos})


async def handle_choose(router: "Router", message: discord.Message, repo_name: str, repo_path: str, session: str, choice: str) -> None:
    """Resolve a pending start conflict."""
    conflict = await router.consume_pending(str(message.channel.id), session)
    if not conflict:
        await router.reply(message.channel, "No pending conflict.")
        return
    choice = choice.lower()
    if choice == "resume":
        await router.reply(message.channel, f"Resuming existing session '{conflict.session}'...")
        await router.handle_resume(message, repo_name, repo_path, conflict.session, "Resumed.")
        return
    if choice == "replace":
        await router.reply(message.channel, f"Replacing session '{conflict.session}' with new start...")
        await router.handle_start(message, repo_name, repo_path, conflict.session)
        return
    if choice == "cancel":
        await router.reply(message.channel, "Cancelled.")
        return
    await router.reply(message.channel, "Unknown choice. Use resume|replace|cancel.")


async def handle_stop(router: "Router", channel: discord.abc.Messageable, session: str) -> None:
    """Send a stop signal to a running Codex process."""
    proc = await router.get_active(str(channel.id), session)
    if proc is not None:
        await proc.stop()
        await asyncio.sleep(0.5)
        await proc.interrupt()
        await router.reply(channel, f"Sent stop (ESC then SIGINT) to session '{session or DEFAULT_SESSION}'.")
        return
    await router.reply(channel, "No running Codex process.")


async def handle_kill(router: "Router", channel: discord.abc.Messageable, session: str) -> None:
    """Force-kill a running Codex process."""
    proc = await router.get_active(str(channel.id), session)
    if proc is not None:
        await proc.kill()
        await router.reply(channel, f"Sent kill to session '{session or DEFAULT_SESSION}'.")
        return
    await router.reply_forbidden(channel, "No running Codex process.")


async def handle_quit(router: "Router", channel: discord.abc.Messageable, session: str) -> None:
    """Send /quit to the Codex process."""
    proc = await router.get_active(str(channel.id), session)
    if proc is not None:
        await proc.write("/quit\n")
        await router.reply(channel, f"Sent /quit to session '{session or DEFAULT_SESSION}'.")
        return
    await router.reply_forbidden(channel, "No running Codex process.")
