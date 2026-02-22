"""Core command handlers for sessions and repo bootstrap."""

from __future__ import annotations

import asyncio
import os
import time
from typing import TYPE_CHECKING

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
    run_limited_command,
    session_exists,
)
from ..transport import MessageEvent, ResponseSink

if TYPE_CHECKING:
    from ..router import Router


async def handle_start(
    router: "Router",
    event: MessageEvent,
    sink: ResponseSink,
    repo_name: str,
    repo_path: str,
    session: str,
) -> None:
    """Start a new Codex session for a channel/session."""
    channel_id = event.channel_id
    session = normalize_session(session)
    state = router.state.load()
    if count_active_sessions(state, channel_id) >= MAX_SESSIONS_PER_CHANNEL:
        if not session_exists(state, channel_id, session):
            await router.reply_forbidden(sink, f"Session limit reached ({MAX_SESSIONS_PER_CHANNEL}). Stop or reuse an existing session.")
            return
    thread_id = existing_thread(state, channel_id, session)
    if thread_id:
        await router.coordinator.set_pending_conflict(
            channel_id,
            session,
            PendingConflict(
                repo_name=repo_name,
                session=session,
                thread_id=thread_id,
                user_id=event.author_id,
                expires_at=time.time() + router.cfg.state.conflict_ttl_seconds,
            ),
        )
        await router.reply(sink, f"Session '{session}' already exists for this channel.\nChoose one:\n!c choose resume\n!c choose replace\n!c choose cancel")
        return

    model, reasoning = _session_model_reasoning_from_state(router, state, channel_id, session)
    args = router.runner.build_start_args(
        repo_path, router.cfg.codex.start_prompt.replace("{{REPO_NAME}}", repo_name), model, reasoning
    )

    async def job() -> None:
        await router.run_codex(event, sink, repo_name, repo_path, session, model, reasoning, args)

    pos, job_id, _ = await router.coordinator.enqueue(channel_id, session, job)
    router.logger.info("enqueue.start", extra={"channel_id": channel_id, "repo": repo_name, "session": session, "job": job_id, "pos": pos})


async def handle_resume(
    router: "Router",
    event: MessageEvent,
    sink: ResponseSink,
    repo_name: str,
    repo_path: str,
    session: str,
    prompt: str,
) -> None:
    """Resume a Codex session with a prompt."""
    channel_id = event.channel_id
    session = normalize_session(session)
    state = router.state.load()
    thread_id = existing_thread(state, channel_id, session)
    model, reasoning = _session_model_reasoning_from_state(router, state, channel_id, session)
    if thread_id:
        args = router.runner.build_resume_args(repo_path, thread_id, prompt, model, reasoning)
    elif session_exists(state, channel_id, session):
        args = router.runner.build_resume_last_args(repo_path, prompt, model, reasoning)
    else:
        # No existing session in this channel: start a fresh run with the prompt.
        args = router.runner.build_start_args(repo_path, prompt, model, reasoning)

    async def job() -> None:
        await router.run_codex(event, sink, repo_name, repo_path, session, model, reasoning, args)

    pos, job_id, _ = await router.coordinator.enqueue(channel_id, session, job)
    router.logger.info("enqueue.resume", extra={"channel_id": channel_id, "repo": repo_name, "session": session, "job": job_id, "pos": pos})


async def handle_create_repo(
    router: "Router",
    event: MessageEvent,
    sink: ResponseSink,
    repo_name: str,
    repo_path: str,
) -> None:
    """Create a new repo directory and git init."""
    channel_id = event.channel_id
    if os.path.isdir(repo_path):
        if os.path.isdir(os.path.join(repo_path, ".git")):
            await router.reply_forbidden(sink, "Repo already exists; use !c start.")
            router.logger.warning("createrepo.exists", extra={"channel_id": channel_id, "repo": repo_name, "path": repo_path})
            return
        await router.reply_forbidden(sink, "Directory already exists and is not a git repo.")
        router.logger.warning("createrepo.exists_non_git", extra={"channel_id": channel_id, "repo": repo_name, "path": repo_path})
        return
    try:
        os.makedirs(repo_path, exist_ok=False)
    except Exception as exc:
        await router.reply_forbidden(sink, f"Create repo dir: {exc}")
        router.logger.error("createrepo.mkdir_failed", extra={"channel_id": channel_id, "repo": repo_name, "error": str(exc)})
        return
    _, err = await run_limited_command(repo_path, ["git", "init"])
    if err:
        await router.reply_forbidden(sink, f"git init failed: {err}")
        router.logger.error("createrepo.git_init_failed", extra={"channel_id": channel_id, "repo": repo_name, "error": str(err)})
        return
    await router.bootstrap_repo_git_config(repo_path)
    try:
        router.seed_agents_template(repo_path)
    except Exception as exc:
        await router.reply_forbidden(sink, str(exc))
        router.logger.error("createrepo.agents_failed", extra={"channel_id": channel_id, "repo": repo_name, "error": str(exc)})
        return
    await router.reply(sink, f"Created repo at {repo_path}")
    router.logger.info("createrepo.ok", extra={"channel_id": channel_id, "repo": repo_name, "path": repo_path})

    session_name = router.current_session_for_user(event.author_id, channel_id)
    try:
        session_name = normalize_session(session_name)
    except ValueError as exc:
        await router.reply_forbidden(sink, str(exc))
        return
    await router.handle_start(event, sink, repo_name, repo_path, session_name)


async def handle_clone_repo(
    router: "Router",
    event: MessageEvent,
    sink: ResponseSink,
    repo_name: str,
    repo_path: str,
    raw_url: str,
) -> None:
    """Clone a GitHub repo into code_root for the channel name."""
    channel_id = event.channel_id
    if os.path.exists(repo_path):
        await router.reply_forbidden(sink, "Repo directory already exists.")
        return
    try:
        clone_url = parse_github_clone_url(raw_url)
    except ValueError as exc:
        await router.reply_forbidden(sink, str(exc))
        return
    _, err = await run_limited_command(os.path.dirname(repo_path), ["git", "clone", clone_url, repo_path], timeout=HELPER_TIMEOUT * 2)
    if err:
        await router.reply_forbidden(sink, f"git clone failed: {err}")
        router.logger.error("clonerepo.failed", extra={"channel_id": channel_id, "repo": repo_name, "url": clone_url, "error": str(err)})
        return
    await router.bootstrap_repo_git_config(repo_path)
    await router.reply(sink, f"Clone complete: {clone_url} -> {repo_path}\nUse `#codex-{repo_name}` for prompts.")
    router.logger.info("clonerepo.ok", extra={"channel_id": channel_id, "repo": repo_name, "url": clone_url, "path": repo_path})


async def handle_copy_repo(
    router: "Router",
    event: MessageEvent,
    sink: ResponseSink,
    repo_name: str,
    repo_path: str,
    new_name: str,
    target_path: str,
) -> None:
    """Copy an existing repo into a new directory without .git."""
    channel_id = event.channel_id
    if os.path.exists(target_path):
        await router.reply_forbidden(sink, "Target repo directory already exists.")
        return
    try:
        copy_dir_excluding_git(repo_path, target_path)
    except Exception as exc:
        await router.reply_forbidden(sink, f"Copy repo failed: {exc}")
        router.logger.error("copyrepo.failed", extra={"channel_id": channel_id, "repo": repo_name, "target": target_path, "error": str(exc)})
        return
    _, err = await run_limited_command(target_path, ["git", "init"])
    if err:
        await router.reply_forbidden(sink, f"git init failed: {err}")
        router.logger.error("copyrepo.git_init_failed", extra={"channel_id": channel_id, "repo": repo_name, "target": target_path, "error": str(err)})
        return
    await router.bootstrap_repo_git_config(target_path)
    await router.reply(sink, f"Copied repo to {target_path}. Continue in #codex-{new_name}")
    router.logger.info("copyrepo.ok", extra={"channel_id": channel_id, "repo": repo_name, "target": target_path})


async def handle_spec(
    router: "Router",
    event: MessageEvent,
    sink: ResponseSink,
    repo_name: str,
    repo_path: str,
    session: str,
) -> None:
    """Run the spec capture flow via Codex."""
    channel_id = event.channel_id
    session = normalize_session(session)
    try:
        os.makedirs(os.path.join(repo_path, "instructions"), exist_ok=True)
    except Exception as exc:
        await router.reply_forbidden(sink, f"Create instructions dir: {exc}")
        return
    state = router.state.load()
    if count_active_sessions(state, channel_id) >= MAX_SESSIONS_PER_CHANNEL and not session_exists(state, channel_id, session):
        await router.reply_forbidden(sink, f"Session limit reached ({MAX_SESSIONS_PER_CHANNEL}). Stop or reuse an existing session.")
        return
    thread_id = existing_thread(state, channel_id, session)
    model, reasoning = _session_model_reasoning_from_state(router, state, channel_id, session)
    prompt = router.spec_prompt(repo_name)
    if thread_id:
        args = router.runner.build_resume_args(repo_path, thread_id, prompt, model, reasoning)
    else:
        args = router.runner.build_start_args(repo_path, prompt, model, reasoning)

    async def job() -> None:
        await router.run_codex(event, sink, repo_name, repo_path, session, model, reasoning, args)

    pos, job_id, _ = await router.coordinator.enqueue(channel_id, session, job)
    router.logger.info("enqueue.spec", extra={"channel_id": channel_id, "repo": repo_name, "session": session, "job": job_id, "pos": pos})


async def handle_choose(
    router: "Router",
    event: MessageEvent,
    sink: ResponseSink,
    repo_name: str,
    repo_path: str,
    session: str,
    choice: str,
) -> None:
    """Resolve a pending start conflict."""
    conflict = await router.consume_pending(event.channel_id, session)
    if not conflict:
        await router.reply(sink, "No pending conflict.")
        return
    choice = choice.lower()
    if choice == "resume":
        await router.reply(sink, f"Resuming existing session '{conflict.session}'...")
        await router.handle_resume(event, sink, repo_name, repo_path, conflict.session, "Resumed.")
        return
    if choice == "replace":
        await router.reply(sink, f"Replacing session '{conflict.session}' with new start...")
        await router.handle_start(event, sink, repo_name, repo_path, conflict.session)
        return
    if choice == "cancel":
        await router.reply(sink, "Cancelled.")
        return
    await router.reply(sink, "Unknown choice. Use resume|replace|cancel.")


async def handle_stop(router: "Router", sink: ResponseSink, session: str) -> None:
    """Send a stop signal to a running Codex process."""
    proc = await router.get_active(sink.channel_id, session)
    if proc is not None:
        await proc.stop()
        await asyncio.sleep(0.5)
        await proc.interrupt()
        await router.reply(
            sink,
            f"Sent stop (ESC then SIGINT) to session '{session or DEFAULT_SESSION}'.{_usage_suffix(router, sink.channel_id, session)}",
        )
        return
    await router.reply(sink, "No running Codex process.")


async def handle_interrupt(router: "Router", sink: ResponseSink, session: str) -> None:
    """Send an interrupt signal (ESC-like) to a running Codex process."""
    proc = await router.get_active(sink.channel_id, session)
    if proc is not None:
        await proc.interrupt()
        await router.reply(
            sink,
            f"Sent interrupt to session '{session or DEFAULT_SESSION}'.{_usage_suffix(router, sink.channel_id, session)}",
        )
        return
    await router.reply(sink, "No running Codex process.")


async def handle_kill(router: "Router", sink: ResponseSink, session: str) -> None:
    """Force-kill a running Codex process."""
    proc = await router.get_active(sink.channel_id, session)
    if proc is not None:
        await proc.kill()
        await router.reply(
            sink,
            f"Sent kill to session '{session or DEFAULT_SESSION}'.{_usage_suffix(router, sink.channel_id, session)}",
        )
        return
    await router.reply_forbidden(sink, "No running Codex process.")


async def handle_quit(router: "Router", sink: ResponseSink, session: str) -> None:
    """Send /quit to the Codex process."""
    proc = await router.get_active(sink.channel_id, session)
    if proc is not None:
        await proc.write("/quit\n")
        await router.reply(
            sink,
            f"Sent /quit to session '{session or DEFAULT_SESSION}'.{_usage_suffix(router, sink.channel_id, session)}",
        )
        return
    await router.reply_forbidden(sink, "No running Codex process.")


async def handle_answer(router: "Router", event: MessageEvent, sink: ResponseSink, session: str, text: str) -> None:
    """Write a user response to the stdin of an active Codex session."""
    try:
        session = normalize_session(session or DEFAULT_SESSION)
    except ValueError as exc:
        await router.reply_forbidden(sink, str(exc))
        return
    payload = (text or "").strip()
    if not payload:
        await router.reply_forbidden(sink, "Answer text required.")
        return
    proc = await router.get_active(sink.channel_id, session)
    if not proc:
        await router.reply_forbidden(
            sink,
            f"No active Codex process for session '{session}'. Start/resume a session first.",
        )
        return
    try:
        await proc.write(payload + "\n")
    except Exception as exc:
        await router.reply_forbidden(sink, f"send input failed: {exc}")
        return
    router.clear_awaiting_input(sink.channel_id, session)
    await router.reply(sink, f"Sent response to session '{session}'.")
    router.logger.info(
        "relay.answer",
        extra={
            "platform": event.platform,
            "channel_id": event.channel_id,
            "repo_channel": event.channel_name,
            "session": session,
            "user_id": event.author_id,
            "chars": len(payload),
        },
    )


async def handle_steer(router: "Router", event: MessageEvent, sink: ResponseSink, session: str, text: str) -> None:
    """Write steering text to stdin of an active Codex session."""
    try:
        session = normalize_session(session or DEFAULT_SESSION)
    except ValueError as exc:
        await router.reply_forbidden(sink, str(exc))
        return
    payload = (text or "").strip()
    if not payload:
        await router.reply_forbidden(
            sink,
            "Cannot steer: text is required. Usage: !c steer [session] -- <text>  or  !c steer <text>",
        )
        return
    proc = await router.get_active(sink.channel_id, session)
    if not proc:
        await router.reply_forbidden(
            sink,
            f"Cannot steer: no active session '{session}' in this channel. Use `!c start` or `!c resume` first.",
        )
        return
    try:
        await proc.write(payload + "\n")
    except Exception as exc:
        await router.reply_forbidden(
            sink,
            f"Steer failed: session process is not accepting input (ended/interrupted). Details: {exc}",
        )
        return
    await router.reply(sink, f"Steer delivered to session '{session}'.")
    router.logger.info(
        "relay.steer",
        extra={
            "platform": event.platform,
            "channel_id": event.channel_id,
            "repo_channel": event.channel_name,
            "session": session,
            "user_id": event.author_id,
            "chars": len(payload),
        },
    )


def _session_model_reasoning_from_state(router: "Router", state, channel_id: str, session: str) -> tuple[str, str]:
    """Resolve model/reasoning for a session using one already-loaded state snapshot."""
    default_model = router.cfg.codex.model
    default_reasoning = router.cfg.codex.model_reasoning_effort
    ch = state.channels.get(channel_id)
    if not ch:
        return default_model, default_reasoning
    sess = ch.sessions.get(session or DEFAULT_SESSION)
    if not sess:
        return default_model, default_reasoning
    model = sess.model or default_model
    reasoning = sess.reasoning_effort or default_reasoning
    return model, reasoning


def _usage_suffix(router: "Router", channel_id: str, session: str) -> str:
    """Render lightweight usage info for end-commands if available."""
    stats = router.get_usage(channel_id, session or DEFAULT_SESSION)
    if not stats:
        return ""
    return f" Usage so far: input {stats.input_tokens}, output {stats.output_tokens}, total {stats.total_tokens}."
