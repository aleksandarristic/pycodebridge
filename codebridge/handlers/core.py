"""Core command handlers for sessions and repo bootstrap."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import os
import time
from typing import TYPE_CHECKING

from ..routing.helpers import (
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
    session_requires_fresh_start,
)
from ..platform.transport import MessageEvent, ResponseSink
from ..services.dm_assistant import DM_ASSISTANT_SESSION

if TYPE_CHECKING:
    from ..routing.router import Router


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
    if router.direct_repo_sessions_enabled():
        if await router.repo_busy(repo_name, exclude_channel_id=channel_id, exclude_session=session):
            await router.reply_forbidden(
                sink,
                f"Repo '{repo_name}' already has a running or queued direct session. "
                "Wait for it to finish or enable `worktrees.session_isolation`.",
            )
            return
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
                reason="start_conflict",
            ),
        )
        await router.reply(
            sink,
            f"Session '{session}' already exists for this channel.\n"
            "Choose one:\n!cont – keep existing session\n!new  – start fresh\n"
            "!compact – summarize prior context, then start fresh",
        )
        return

    model, reasoning = _session_model_reasoning_from_state(router, state, channel_id, session)
    backend = _session_backend_from_state(router, state, channel_id, session)
    router.coordinator.update_state(channel_id, session, repo_name, repo_path, thread_id or "", model, reasoning)
    args = backend.build_start_args(
        repo_path, router.cfg.codex.start_prompt.replace("{{REPO_NAME}}", repo_name), model, reasoning
    )

    async def job() -> None:
        await router.run_codex(event, sink, repo_name, repo_path, session, model, reasoning, args, backend=backend)

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
    skip_idle_ttl_check: bool = False,
) -> None:
    """Resume a Codex session with a prompt."""
    channel_id = event.channel_id
    session = normalize_session(session)
    if router.direct_repo_sessions_enabled():
        if await router.repo_busy(repo_name, exclude_channel_id=channel_id, exclude_session=session):
            await router.reply_forbidden(
                sink,
                f"Repo '{repo_name}' already has a running or queued direct session. "
                "Wait for it to finish or enable `worktrees.session_isolation`.",
            )
            return
    state = router.state.load()
    idle_ttl_seconds = max(0, int(getattr(router.cfg.state, "session_idle_ttl_seconds", 0) or 0))
    sess = state.channels.get(channel_id).sessions.get(session) if state.channels.get(channel_id) else None
    if sess and idle_ttl_seconds > 0 and not skip_idle_ttl_check:
        idle_seconds = _session_idle_seconds(sess.last_used_at or sess.created_at)
        if idle_seconds >= idle_ttl_seconds:
            router.logger.info(
                "session.expired",
                extra={"channel_id": channel_id, "session": session, "idle_seconds": idle_seconds},
            )
            thread_id = existing_thread(state, channel_id, session) or ""
            await router.coordinator.set_pending_conflict(
                channel_id,
                session,
                PendingConflict(
                    repo_name=repo_name,
                    session=session,
                    thread_id=thread_id,
                    user_id=event.author_id,
                    expires_at=time.time() + router.cfg.state.conflict_ttl_seconds,
                    reason="session_expired",
                    prompt=prompt or "",
                ),
            )
            await router.reply(
                sink,
                f"Session '{session}' expired (idle {router._format_duration(idle_seconds)}). What would you like to do?\n"
                "!cont    – resume where you left off\n"
                "!compact – summarize context, then start fresh\n"
                "!new     – start completely fresh",
            )
            return
    thread_id = existing_thread(state, channel_id, session)
    model, reasoning = _session_model_reasoning_from_state(router, state, channel_id, session)
    backend = _session_backend_from_state(router, state, channel_id, session)
    router.coordinator.update_state(channel_id, session, repo_name, repo_path, thread_id or "", model, reasoning)
    if thread_id:
        args = backend.build_resume_args(repo_path, thread_id, prompt, model, reasoning)
    elif (
        session_exists(state, channel_id, session)
        and not session_requires_fresh_start(state, channel_id, session)
    ):
        args = backend.build_resume_last_args(repo_path, prompt, model, reasoning)
    else:
        # No resumable channel thread/history is available: start a fresh run with the prompt.
        args = backend.build_start_args(repo_path, prompt, model, reasoning)

    async def job() -> None:
        await router.run_codex(event, sink, repo_name, repo_path, session, model, reasoning, args, backend=backend)

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
        router.bootstrap_agent_env_cache(repo_path)
        router.seed_agents_template(repo_path)
    except Exception as exc:
        await router.reply_forbidden(sink, str(exc))
        router.logger.error("createrepo.bootstrap_failed", extra={"channel_id": channel_id, "repo": repo_name, "error": str(exc)})
        return
    await router.reply(sink, f"Created repo at {repo_path}")
    router.logger.info("createrepo.ok", extra={"channel_id": channel_id, "repo": repo_name, "path": repo_path})

    session_name = router.current_session_for_event(event)
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
    try:
        router.bootstrap_agent_env_cache(repo_path)
    except Exception as exc:
        await router.reply_forbidden(sink, str(exc))
        router.logger.error("clonerepo.bootstrap_failed", extra={"channel_id": channel_id, "repo": repo_name, "error": str(exc)})
        return
    await router.reply(sink, f"Clone complete: {clone_url} -> {repo_path}\nUse `#code-{repo_name}` for prompts.")
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
    try:
        router.bootstrap_agent_env_cache(target_path)
    except Exception as exc:
        await router.reply_forbidden(sink, str(exc))
        router.logger.error("copyrepo.bootstrap_failed", extra={"channel_id": channel_id, "repo": repo_name, "target": target_path, "error": str(exc)})
        return
    await router.reply(sink, f"Copied repo to {target_path}. Continue in #code-{new_name}")
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
    backend = _session_backend_from_state(router, state, channel_id, session)
    prompt = router.spec_prompt(repo_name)
    if thread_id:
        args = backend.build_resume_args(repo_path, thread_id, prompt, model, reasoning)
    else:
        args = backend.build_start_args(repo_path, prompt, model, reasoning)

    async def job() -> None:
        await router.run_codex(event, sink, repo_name, repo_path, session, model, reasoning, args, backend=backend)

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
    choice = (choice or "").strip().lower()
    aliases = {
        "continue": "resume",
        "cont": "resume",
        "new": "replace",
        "start": "replace",
        "compact": "compact",
        "summary": "compact",
    }
    choice = aliases.get(choice, choice)
    if choice not in {"resume", "replace", "compact"}:
        await router.reply_forbidden(sink, "Usage: !c choose [session] continue|new|compact")
        await router.coordinator.set_pending_conflict(event.channel_id, conflict.session, conflict)
        return
    if choice == "resume":
        resume_prompt = (conflict.prompt or "").strip() or "Resumed."
        await router.reply(sink, f"Continuing session '{conflict.session}'...")
        await router.handle_resume(
            event,
            sink,
            repo_name,
            repo_path,
            conflict.session,
            resume_prompt,
            skip_idle_ttl_check=True,
        )
        return
    if choice == "compact":
        state = router.state.load()
        model, reasoning = _session_model_reasoning_from_state(router, state, event.channel_id, conflict.session)
        backend = _session_backend_from_state(router, state, event.channel_id, conflict.session)
        start_prompt = router.build_compacted_session_prompt(
            event.channel_id,
            conflict.session,
            repo_name,
            repo_path,
            (conflict.prompt or "").strip(),
        )
        router.clear_session_thread(event.channel_id, conflict.session, fresh_start_required=True)
        args = backend.build_start_args(repo_path, start_prompt, model, reasoning)

        async def job() -> None:
            await router.run_codex(event, sink, repo_name, repo_path, conflict.session, model, reasoning, args, backend=backend)

        pos, job_id, _ = await router.coordinator.enqueue(event.channel_id, conflict.session, job)
        router.logger.info(
            "enqueue.start_compact",
            extra={
                "channel_id": event.channel_id,
                "repo": repo_name,
                "session": conflict.session,
                "job": job_id,
                "pos": pos,
                "reason": conflict.reason,
            },
        )
        await router.reply(sink, f"Starting a compact new session in '{conflict.session}'...")
        return
    used_fallback_replace = choice != "replace"
    state = router.state.load()
    model, reasoning = _session_model_reasoning_from_state(router, state, event.channel_id, conflict.session)
    backend = _session_backend_from_state(router, state, event.channel_id, conflict.session)
    start_prompt = router.cfg.codex.start_prompt.replace("{{REPO_NAME}}", repo_name)
    router.clear_session_thread(event.channel_id, conflict.session, fresh_start_required=True)
    args = backend.build_start_args(repo_path, start_prompt, model, reasoning)

    async def job() -> None:
        await router.run_codex(event, sink, repo_name, repo_path, conflict.session, model, reasoning, args, backend=backend)

    pos, job_id, _ = await router.coordinator.enqueue(event.channel_id, conflict.session, job)
    router.logger.info(
        "enqueue.start_replace_fallback" if used_fallback_replace else "enqueue.start_replace",
        extra={
            "channel_id": event.channel_id,
            "repo": repo_name,
            "session": conflict.session,
            "job": job_id,
            "pos": pos,
            "reason": conflict.reason,
        },
    )
    await router.reply(sink, f"Starting a new session in '{conflict.session}'...")


def _session_idle_seconds(timestamp: str) -> int:
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


async def _no_active_agent_reply(router: "Router", sink: ResponseSink, session: str) -> None:
    sess_label = session or DEFAULT_SESSION
    active = await router.active_sessions(sink.channel_id)
    if active:
        hint = f" Active sessions: {', '.join(sorted(active))}."
    else:
        hint = ""
    await router.reply_forbidden(sink, f"No agent running in session '{sess_label}'.{hint}")


async def handle_stop(router: "Router", sink: ResponseSink, session: str) -> None:
    """Send a stop signal to a running agent process."""
    proc = await router.get_active(sink.channel_id, session)
    if proc is not None:
        await proc.stop()
        await asyncio.sleep(0.5)
        proc.interrupt()
        await router.reply(
            sink,
            f"Sent stop (ESC then SIGINT) to session '{session or DEFAULT_SESSION}'.{_usage_suffix(router, sink.channel_id, session)}",
        )
        return
    await _no_active_agent_reply(router, sink, session)


async def handle_interrupt(router: "Router", sink: ResponseSink, session: str) -> None:
    """Send ESC to interrupt a running agent process."""
    proc = await router.get_active(sink.channel_id, session)
    if proc is not None:
        await proc.stop()
        await router.reply(
            sink,
            f"Sent interrupt (ESC) to session '{session or DEFAULT_SESSION}'.{_usage_suffix(router, sink.channel_id, session)}",
        )
        return
    await _no_active_agent_reply(router, sink, session)


async def handle_kill(router: "Router", sink: ResponseSink, session: str) -> None:
    """Force-kill a running agent process."""
    proc = await router.get_active(sink.channel_id, session)
    if proc is not None:
        proc.kill()
        await router.reply(
            sink,
            f"Sent kill to session '{session or DEFAULT_SESSION}'.{_usage_suffix(router, sink.channel_id, session)}",
        )
        return
    # Process already gone but bridge state may still be dirty — recover it.
    if await router.recover_orphaned_run(sink.channel_id, session):
        sess_label = session or DEFAULT_SESSION
        await router.reply(
            sink,
            f"Session '{sess_label}': process had already exited but state was stale — cleared. Use `!c reset` if the session behaves unexpectedly.",
        )
        return
    await _no_active_agent_reply(router, sink, session)


async def handle_quit(router: "Router", sink: ResponseSink, session: str) -> None:
    """Send /quit to the active agent process."""
    proc = await router.get_active(sink.channel_id, session)
    if proc is not None:
        await proc.write("/quit\n")
        await router.reply(
            sink,
            f"Sent /quit to session '{session or DEFAULT_SESSION}'.{_usage_suffix(router, sink.channel_id, session)}",
        )
        return
    await _no_active_agent_reply(router, sink, session)


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
            f"No active agent process for session '{session}'. Start/resume a session first.",
        )
        return
    try:
        await proc.write(payload + "\n")
    except Exception as exc:
        await router.reply_forbidden(sink, f"send input failed: {exc}")
        return
    router.clear_awaiting_input(sink.channel_id, session)
    try:
        await router.reply(sink, f"Sent response to session '{session}'.")
    except Exception as exc:
        router.logger.warning(
            "relay.answer_ack_failed",
            extra={"channel_id": sink.channel_id, "session": session, "error": str(exc)},
        )
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
    try:
        await router.reply(sink, f"Steer delivered to session '{session}'.")
    except Exception as exc:
        router.logger.warning(
            "relay.steer_ack_failed",
            extra={"channel_id": sink.channel_id, "session": session, "error": str(exc)},
        )
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


async def handle_unpin(router: "Router", event: MessageEvent, sink: ResponseSink) -> None:
    """Unpin all but the most recently pinned message in the current channel."""
    message = getattr(event, "raw_event", None)
    channel = getattr(message, "channel", None) if message is not None else None
    if channel is None or not callable(getattr(channel, "pins", None)):
        await router.reply_forbidden(sink, "Unpin is not supported in this context.")
        return
    try:
        pins = await channel.pins()
    except Exception as exc:
        await router.reply_forbidden(sink, f"Could not fetch pins: {exc}")
        return
    if len(pins) <= 1:
        noun = "pin" if len(pins) == 1 else "pins"
        await router.reply(sink, f"Nothing to remove ({len(pins)} {noun} in this channel).")
        return
    to_remove = pins[:-1]
    removed = 0
    for msg in to_remove:
        try:
            await msg.unpin()
            removed += 1
        except Exception:
            pass
    kept = len(pins) - removed
    await router.reply(
        sink,
        f"Removed {removed} old pin{'s' if removed != 1 else ''}"
        f"{', kept ' + str(kept) if kept else ''}."
        if removed else "No pins could be removed (permission error?).",
    )
    router.logger.info(
        "relay.unpin",
        extra={
            "platform": event.platform,
            "channel_id": event.channel_id,
            "user_id": event.author_id,
            "removed": removed,
            "total": len(pins),
        },
    )


async def handle_unpin_all_channels(router: "Router", sink: ResponseSink) -> None:
    """Unpin all but the last pin in every channel matching the configured regex."""
    fn = getattr(router, "_guild_text_channels_fn", None)
    if not callable(fn):
        await router.reply_forbidden(sink, "Unpin-all is not available (no guild channel access wired up).")
        return
    try:
        channels = await fn()
    except Exception as exc:
        await router.reply_forbidden(sink, f"Could not list guild channels: {exc}")
        return
    regex = router.cfg.channel_regex()
    results: list[str] = []
    for ch in channels:
        name = str(getattr(ch, "name", "") or "")
        if not regex.match(name):
            continue
        try:
            pins = await ch.pins()
        except Exception as exc:
            results.append(f"{name}: error fetching pins ({exc})")
            continue
        if len(pins) <= 1:
            noun = "pin" if len(pins) == 1 else "pins"
            results.append(f"{name}: {len(pins)} {noun}, nothing to remove")
            continue
        to_remove = pins[:-1]
        removed = 0
        for msg in to_remove:
            try:
                await msg.unpin()
                removed += 1
            except Exception:
                pass
        results.append(f"{name}: removed {removed}/{len(to_remove)} old pin{'s' if len(to_remove) != 1 else ''}")
    if not results:
        await router.reply(sink, "No matching channels found.")
        return
    await router.reply(sink, "\n".join(results))


def _session_model_reasoning_from_state(router: "Router", state, channel_id: str, session: str) -> tuple[str, str]:
    """Resolve model/reasoning for a session using one already-loaded state snapshot."""
    ch = state.channels.get(channel_id)
    sess = ch.sessions.get(session or DEFAULT_SESSION) if ch else None
    is_dm_assistant = session == DM_ASSISTANT_SESSION and router.cfg.dm_assistant.enabled
    backend_name = (sess.backend if sess else "") or (
        router.cfg.dm_assistant.default_backend if is_dm_assistant and router.cfg.dm_assistant.default_backend else ""
    ) or router.cfg.agent.default_backend
    if backend_name == "claude":
        default_model = router.cfg.claude.model
        default_reasoning = router.cfg.claude.effort
    elif backend_name == "gemini":
        default_model = router.cfg.gemini.model
        default_reasoning = ""
    else:
        default_model = router.cfg.codex.model
        default_reasoning = router.cfg.codex.model_reasoning_effort
    if is_dm_assistant:
        default_model = router.cfg.dm_assistant.model or default_model
        default_reasoning = router.cfg.dm_assistant.effort or default_reasoning
    if not sess:
        return default_model, default_reasoning
    model = sess.model or default_model
    reasoning = sess.reasoning_effort or default_reasoning
    return model, reasoning


def _session_backend_from_state(router: "Router", state, channel_id: str, session: str):
    """Resolve the AgentBackend for a session using one already-loaded state snapshot.

    Returns router.runner when no explicit backend override is set so tests can
    inject a fake runner without needing to monkeypatch the factory.
    """
    ch = state.channels.get(channel_id)
    if ch:
        sess = ch.sessions.get(session or DEFAULT_SESSION)
        if sess and sess.backend:
            from ..agents.factory import build_backend
            return build_backend(router.cfg, sess.backend)
    if session == DM_ASSISTANT_SESSION and router.cfg.dm_assistant.enabled:
        backend_name = (router.cfg.dm_assistant.default_backend or "").strip()
        if backend_name and backend_name != router.cfg.agent.default_backend:
            from ..agents.factory import build_backend
            return build_backend(router.cfg, backend_name)
    return router.runner


def _usage_suffix(router: "Router", channel_id: str, session: str) -> str:
    """Render lightweight usage info for end-commands if available."""
    stats = router.get_usage(channel_id, session or DEFAULT_SESSION)
    if not stats:
        return ""
    return f" Usage so far: input {stats.input_tokens}, output {stats.output_tokens}, total {stats.total_tokens}."
