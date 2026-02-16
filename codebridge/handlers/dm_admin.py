"""DM admin command handlers."""

from __future__ import annotations

import os
import time
from typing import TYPE_CHECKING, Optional

from ..audit import Entry
from ..router_helpers import (
    DEFAULT_SESSION,
    HELPER_TIMEOUT,
    copy_dir_excluding_git,
    forbidden_message,
    parse_github_clone_url,
    prune_state_for_repo,
    rename_state_repo,
    run_limited_command,
)
from ..state import utc_now_iso
from ..transport import Capabilities, MessageEvent, ResponseSink
from ..util import path as pathutil

if TYPE_CHECKING:
    from ..router import Router


class _PrefixedSink:
    """Response sink wrapper that prefixes messages with a repo name."""

    def __init__(self, sink: ResponseSink, repo_name: str) -> None:
        self._sink = sink
        self._repo_name = repo_name
        self.channel_id = sink.channel_id

    async def send(self, content: str, thread_id: str | None = None, reply_to_id: str | None = None) -> None:
        await self._sink.send(f"[{self._repo_name}] {content}", thread_id=thread_id, reply_to_id=reply_to_id)

    def capabilities(self) -> Capabilities:
        return self._sink.capabilities()

    def typing(self):  # type: ignore[override]
        return self._sink.typing()

    async def update_pinned_status(self, user_id: str, session: str, text: str) -> None:
        await self._sink.update_pinned_status(user_id, session, text)

    async def send_file(self, path: str, filename: str, thread_id: str | None = None, reply_to_id: str | None = None) -> None:
        await self._sink.send_file(path, filename, thread_id=thread_id, reply_to_id=reply_to_id)


def dm_help_text() -> str:
    """Return DM admin help text."""
    return (
        "DM Admin:\n"
        "help — show this help\n"
        "repos — list repos under code_root\n"
        "sessions — list sessions across channels\n"
        "status — show queues and running jobs\n"
        "config — show effective config\n"
        "gh <args> — run GitHub CLI in DM context\n"
        "createrepo <name> — create repo\n"
        "clonerepo <name> <url> — clone repo\n"
        "copyrepo <from> <to> — copy repo\n"
        "deleterepo <name> — delete repo\n"
        "renamerepo <from> <to> — rename repo\n"
    )


def dm_binding_help_text() -> str:
    """Return DM repo binding help text."""
    return (
        "DM Repo Binding:\n"
        "bind <repo> — bind this DM to a repo\n"
        "use <repo> — alias for bind\n"
        "repo <repo> <prompt> — run a one-off prompt against a repo\n"
        "gh <args> — run GitHub CLI (bound repo cwd, or code_root if unbound)\n"
        "unbind — clear bound repo\n"
        "status — show current bound repo and session\n"
    )


async def dm_reply(router: "Router", sink: ResponseSink, entry: Optional[Entry], msg: str) -> None:
    """Send a DM reply and record it to audit logs."""
    router.append_audit_output(entry, msg)
    await sink.send(msg)


def dm_audit_start(router: "Router", event: MessageEvent, cmd: str, rest: str) -> Optional[Entry]:
    """Start a DM audit entry for admin commands."""
    meta = {
        "command": cmd,
        "args": rest,
        "timestamp": utc_now_iso(),
        "channel": f"dm-{event.author_id}",
    }
    return router.audit_start(f"dm-{event.author_id}", "admin", "dm", meta)


async def dm_list_repos(router: "Router") -> str:
    """List repos under code_root with last modified time."""
    base = router.cfg.codex.code_root
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


async def dm_list_sessions(router: "Router") -> str:
    """List all sessions across channels."""
    state = router.state.load()
    lines = []
    for channel_id, ch in state.channels.items():
        for name, sess in ch.sessions.items():
            lines.append(f"channel {channel_id} repo {sess.repo_name} session {name} last {sess.last_used_at}")
    return "\n".join(lines) if lines else "No sessions found."


async def dm_status(router: "Router") -> str:
    """Return a summary of queued/running jobs across channels."""
    snapshots = await router.coordinator.snapshot_all()
    lines = []
    for channel_id, statuses in snapshots.items():
        for st in statuses:
            lines.append(f"{channel_id}: {st.job_id} [{st.status}] session:{st.session or DEFAULT_SESSION} pos:{st.position}")
    return "\n".join(lines) if lines else "No queued or running jobs."


async def dm_create_repo(
    router: "Router",
    event: MessageEvent,
    sink: ResponseSink,
    repo_name: str,
    entry: Optional[Entry],
) -> Optional[Exception]:
    """Create a new repo via DM admin command."""
    repo_name = pathutil.normalize_repo_name(repo_name)
    try:
        repo_path = pathutil.resolve_repo_path_for_create(router.cfg.codex.code_root, repo_name)
    except Exception as exc:
        return exc
    if os.path.isdir(repo_path):
        if os.path.isdir(os.path.join(repo_path, ".git")):
            return RuntimeError("Repo already exists.")
        return RuntimeError("Directory already exists and is not a git repo.")
    try:
        os.makedirs(repo_path, exist_ok=False)
    except Exception as exc:
        return exc
    _, err = await run_limited_command(repo_path, ["git", "init"])
    if err:
        return err
    try:
        router.seed_agents_template(repo_path)
    except Exception as exc:
        return exc
    await dm_reply(router, sink, entry, f"Created repo at {repo_path}. Continue in #codex-{repo_name}")
    router.logger.info("dm.bind.createrepo", extra={"platform": event.platform, "user_id": event.author_id, "repo": repo_name})
    router.logger.info("dm.createrepo.ok", extra={"user_id": event.author_id, "repo": repo_name, "path": repo_path})
    return None


async def dm_clone_repo(
    router: "Router",
    event: MessageEvent,
    sink: ResponseSink,
    repo_name: str,
    raw_url: str,
    entry: Optional[Entry],
) -> Optional[Exception]:
    """Clone a repo via DM admin command."""
    repo_name = pathutil.normalize_repo_name(repo_name)
    try:
        repo_path = pathutil.resolve_repo_path_for_create(router.cfg.codex.code_root, repo_name)
    except Exception as exc:
        return exc
    if os.path.exists(repo_path):
        return RuntimeError("Repo directory already exists.")
    try:
        clone_url = parse_github_clone_url(raw_url)
    except ValueError as exc:
        return exc
    _, err = await run_limited_command(os.path.dirname(repo_path), ["git", "clone", clone_url, repo_path], timeout=HELPER_TIMEOUT * 2)
    if err:
        return err
    await dm_reply(router, sink, entry, f"Cloned {clone_url} into {repo_path}. Continue in #codex-{repo_name}")
    router.logger.info("dm.bind.clonerepo", extra={"platform": event.platform, "user_id": event.author_id, "repo": repo_name})
    router.logger.info("dm.clonerepo.ok", extra={"user_id": event.author_id, "repo": repo_name, "url": clone_url, "path": repo_path})
    return None


async def dm_copy_repo(
    router: "Router",
    event: MessageEvent,
    sink: ResponseSink,
    from_name: str,
    to_name: str,
    entry: Optional[Entry],
) -> Optional[Exception]:
    """Copy a repo via DM admin command."""
    from_name = pathutil.normalize_repo_name(from_name)
    to_name = pathutil.normalize_repo_name(to_name)
    try:
        src_path = pathutil.resolve_repo_path(router.cfg.codex.code_root, from_name)
        dst_path = pathutil.resolve_repo_path_for_create(router.cfg.codex.code_root, to_name)
    except Exception as exc:
        return exc
    if os.path.exists(dst_path):
        return RuntimeError("Target repo directory already exists.")
    try:
        copy_dir_excluding_git(src_path, dst_path)
    except Exception as exc:
        return exc
    _, err = await run_limited_command(dst_path, ["git", "init"])
    if err:
        return err
    await dm_reply(router, sink, entry, f"Copied repo to {dst_path}. Continue in #codex-{to_name}")
    router.logger.info("dm.bind.copyrepo", extra={"platform": event.platform, "user_id": event.author_id, "repo": to_name})
    router.logger.info("dm.copyrepo.ok", extra={"user_id": event.author_id, "repo": from_name, "target": dst_path})
    return None


async def dm_delete_repo(
    router: "Router",
    event: MessageEvent,
    sink: ResponseSink,
    repo_name: str,
    entry: Optional[Entry],
) -> Optional[Exception]:
    """Delete a repo via DM admin command."""
    repo_name = pathutil.normalize_repo_name(repo_name)
    try:
        repo_path = pathutil.resolve_repo_path(router.cfg.codex.code_root, repo_name)
    except Exception as exc:
        return exc
    if await router.repo_busy(repo_name):
        return RuntimeError("Repo has active or queued jobs. Stop/kill them first.")
    try:
        for root, dirs, files in os.walk(repo_path, topdown=False):
            for name in files:
                os.remove(os.path.join(root, name))
            for name in dirs:
                os.rmdir(os.path.join(root, name))
        os.rmdir(repo_path)
    except Exception as exc:
        return exc
    router.state.update(lambda fs: prune_state_for_repo(fs, repo_name, repo_path))
    await dm_reply(router, sink, entry, f"Deleted repo {repo_name}")
    router.logger.info("dm.bind.deleterepo", extra={"platform": event.platform, "user_id": event.author_id, "repo": repo_name})
    router.logger.info("dm.deleterepo.ok", extra={"user_id": event.author_id, "repo": repo_name})
    return None


async def dm_rename_repo(
    router: "Router",
    event: MessageEvent,
    sink: ResponseSink,
    from_name: str,
    to_name: str,
    entry: Optional[Entry],
) -> Optional[Exception]:
    """Rename a repo via DM admin command."""
    from_name = pathutil.normalize_repo_name(from_name)
    to_name = pathutil.normalize_repo_name(to_name)
    try:
        src_path = pathutil.resolve_repo_path(router.cfg.codex.code_root, from_name)
        dst_path = pathutil.resolve_repo_path_for_create(router.cfg.codex.code_root, to_name)
    except Exception as exc:
        return exc
    if await router.repo_busy(from_name):
        return RuntimeError("Repo has active or queued jobs. Stop/kill them first.")
    if os.path.exists(dst_path):
        return RuntimeError("Target repo directory already exists.")
    try:
        os.rename(src_path, dst_path)
    except Exception as exc:
        return exc
    router.state.update(lambda fs: rename_state_repo(fs, from_name, src_path, to_name, dst_path))
    await dm_reply(router, sink, entry, f"Renamed repo {from_name} to {to_name}. Continue in #codex-{to_name}")
    router.logger.info("dm.bind.renamerepo", extra={"platform": event.platform, "user_id": event.author_id, "repo": to_name})
    router.logger.info("dm.renamerepo.ok", extra={"user_id": event.author_id, "repo": from_name, "target": dst_path})
    return None


async def handle_dm_message(router: "Router", event: MessageEvent, sink: ResponseSink) -> None:
    """Handle an incoming DM admin message."""
    content = (event.content or "").strip()
    prefix = router._transport_prefix(event)
    pending_upload = False
    file_transfers = getattr(router, "file_transfers", None)
    if file_transfers is not None and hasattr(file_transfers, "has_pending_upload"):
        pending_upload = file_transfers.has_pending_upload(event)
    pending_content = content
    if pending_upload and router._totp_enabled(event):
        ok, pending_content = await router.require_totp(event, sink, "upload", content)
        if not ok:
            return
    if await router.handle_pending_upload_response(event, sink, router.get_dm_binding(event) or "", pending_content):
        return
    if not content.startswith(prefix):
        relay_session, ambiguous = await router.pending_input_session(event)
        if ambiguous:
            await sink.send(forbidden_message("Multiple sessions are waiting for input. Use `!c answer <session> -- <text>`."))
            return
        if relay_session and not event.attachments:
            relay_text = content.strip()
            if not relay_text:
                return
            if router._totp_enabled(event):
                ok, relay_text = await router.require_totp(event, sink, "answer", relay_text)
                if not ok:
                    return
            await router.handle_answer(event, sink, relay_session, relay_text)
            return
        if not router._transport_user_allowed(event):
            await sink.send(forbidden_message("You are not allowed to use this bot."))
            return
        bound_repo = router.get_dm_binding(event)
        if not bound_repo:
            await sink.send("No repo bound. Send `!c repos` to list and then `!c bind <repo>` to bind a repo. Send `!c help` for instructions.")
            return
        try:
            repo_path = pathutil.resolve_repo_path(router.cfg.codex.code_root, bound_repo)
        except Exception as exc:
            await sink.send(forbidden_message(f"Repo error: {exc}"))
            return
        if event.attachments:
            if router._totp_enabled(event):
                ok, _ = await router.require_totp(event, sink, "upload", content)
                if not ok:
                    return
            await router.handle_upload_request(event, sink, bound_repo, repo_path)
            return
        session = router.current_session_for_user(event.author_id, event.channel_id)
        prefixed_sink = _PrefixedSink(sink, bound_repo)
        if router._totp_enabled(event):
            ok, content = await router.require_totp(event, sink, "resume", content)
            if not ok:
                return
        await router.handle_resume(event, prefixed_sink, bound_repo, repo_path, session, content)
        return
    cmdline = content[len(prefix) :].strip()
    if not cmdline:
        return
    fields = cmdline.split()
    cmd = fields[0].lower()
    rest = cmdline[len(fields[0]) :].strip()

    entry = dm_audit_start(router, event, cmd, rest)

    async def send(text: str) -> None:
        await dm_reply(router, sink, entry, text)

    async def send_forbidden(detail: str) -> None:
        await dm_reply(router, sink, entry, forbidden_message(detail))

    is_admin = event.platform == "discord" and router.cfg.discord.dm_admin_enabled and router._dm_admin_allowed(event.author_id)
    binding_commands = {"bind", "use", "repo", "unbind", "status"}
    admin_commands = {
        "help",
        "repos",
        "sessions",
        "config",
        "createrepo",
        "clonerepo",
        "copyrepo",
        "deleterepo",
        "delete",
        "renamerepo",
        "rename",
    }

    if cmd in admin_commands:
        if not is_admin:
            await send_forbidden("You are not allowed to use DM admin commands.")
            return
        if cmd in {"createrepo", "clonerepo", "copyrepo", "deleterepo", "delete", "renamerepo", "rename"}:
            ok, cmdline = await router.require_totp(event, sink, cmd, cmdline)
            if not ok:
                return
            fields = cmdline.split()
            if not fields:
                return
            cmd = fields[0].lower()
            rest = cmdline[len(fields[0]) :].strip()
        router.logger.info(
            "dm.admin",
            extra={"platform": event.platform, "user_id": event.author_id, "cmd": cmd},
        )
        if cmd == "help":
            await send(dm_help_text())
            return
        if cmd == "repos":
            msg = await dm_list_repos(router)
            await send(msg)
            return
        if cmd == "sessions":
            msg = await dm_list_sessions(router)
            await send(msg)
            return
        if cmd == "config":
            await send(router.config_text())
            return
        if cmd == "createrepo":
            name = rest.strip()
            if not name:
                await send_forbidden("Usage: !c createrepo <name>")
                return
            err = await dm_create_repo(router, event, sink, name, entry)
            if err:
                await send_forbidden(str(err))
            return
        if cmd == "clonerepo":
            parts = rest.split(maxsplit=1)
            if len(parts) < 2:
                await send_forbidden("Usage: !c clonerepo <name> <url>")
                return
            err = await dm_clone_repo(router, event, sink, parts[0], parts[1], entry)
            if err:
                await send_forbidden(str(err))
            return
        if cmd == "copyrepo":
            parts = rest.split(maxsplit=1)
            if len(parts) < 2:
                await send_forbidden("Usage: !c copyrepo <from> <to>")
                return
            err = await dm_copy_repo(router, event, sink, parts[0], parts[1], entry)
            if err:
                await send_forbidden(str(err))
            return
        if cmd in {"deleterepo", "delete"}:
            name = rest.strip()
            if not name:
                await send_forbidden("Usage: !c deleterepo <name>")
                return
            err = await dm_delete_repo(router, event, sink, name, entry)
            if err:
                await send_forbidden(str(err))
            return
        if cmd in {"renamerepo", "rename"}:
            parts = rest.split(maxsplit=1)
            if len(parts) < 2:
                await send_forbidden("Usage: !c renamerepo <from> <to>")
                return
            err = await dm_rename_repo(router, event, sink, parts[0], parts[1], entry)
            if err:
                await send_forbidden(str(err))
            return
        return

    if cmd in binding_commands:
        if not router._transport_user_allowed(event):
            await send_forbidden("You are not allowed to use this bot.")
            return
        if cmd in {"bind", "use", "repo", "unbind"}:
            ok, cmdline = await router.require_totp(event, sink, cmd, cmdline)
            if not ok:
                return
            fields = cmdline.split()
            if not fields:
                return
            cmd = fields[0].lower()
            rest = cmdline[len(fields[0]) :].strip()
        if cmd == "status":
            bound = router.get_dm_binding(event)
            session = router.current_session_for_user(event.author_id, event.channel_id)
            info = f"Bound repo: {bound or 'none'}\nCurrent session: {session}"
            if is_admin:
                status = await dm_status(router)
                if status:
                    info = info + "\n\nAdmin status:\n" + status
            await send(info)
            router.logger.info(
                "dm.status",
                extra={"platform": event.platform, "user_id": event.author_id, "repo": bound or "", "session": session},
            )
            return
        if cmd in {"bind", "use"}:
            repo_name = rest.strip()
            if not repo_name:
                await send_forbidden("Usage: !c bind <repo>")
                return
            try:
                repo_name = pathutil.normalize_repo_name(repo_name)
                _ = pathutil.resolve_repo_path(router.cfg.codex.code_root, repo_name)
            except Exception as exc:
                await send_forbidden(f"Repo error: {exc}")
                return
            router.set_dm_binding(event, repo_name)
            await send(f"Bound repo: {repo_name}")
            router.logger.info(
                "dm.bind",
                extra={"platform": event.platform, "user_id": event.author_id, "repo": repo_name},
            )
            return
        if cmd == "unbind":
            router.clear_dm_binding(event)
            await send("Repo binding cleared.")
            router.logger.info(
                "dm.unbind",
                extra={"platform": event.platform, "user_id": event.author_id},
            )
            return
        if cmd == "repo":
            parts = rest.split(maxsplit=1)
            if len(parts) < 2:
                await send_forbidden("Usage: !c repo <repo> <prompt>")
                return
            repo_name = parts[0]
            prompt = parts[1].strip()
            if not prompt:
                await send_forbidden("Prompt required.")
                return
            try:
                repo_name = pathutil.normalize_repo_name(repo_name)
                repo_path = pathutil.resolve_repo_path(router.cfg.codex.code_root, repo_name)
            except Exception as exc:
                await send_forbidden(f"Repo error: {exc}")
                return
            session = router.current_session_for_user(event.author_id, event.channel_id)
            prefixed_sink = _PrefixedSink(sink, repo_name)
            router.logger.info(
                "dm.repo",
                extra={"platform": event.platform, "user_id": event.author_id, "repo": repo_name, "session": session},
            )
            await router.handle_resume(event, prefixed_sink, repo_name, repo_path, session, prompt)
            return
        await send(dm_binding_help_text())
        return

    if cmd == "gh":
        if not router._transport_user_allowed(event):
            await send_forbidden("You are not allowed to use this bot.")
            return
        ok, cmdline = await router.require_totp(event, sink, cmd, cmdline)
        if not ok:
            return
        fields = cmdline.split()
        if not fields:
            return
        rest = cmdline[len(fields[0]) :].strip()
        if not rest.strip():
            await send_forbidden("Usage: !c gh <args>")
            return
        bound_repo = router.get_dm_binding(event)
        run_path = router.cfg.codex.code_root
        if bound_repo:
            try:
                run_path = pathutil.resolve_repo_path(router.cfg.codex.code_root, bound_repo)
            except Exception as exc:
                await send_forbidden(f"Repo error: {exc}")
                return
        await router.handle_gh(sink, run_path, rest)
        return

    if cmd in {"answer", "approve", "deny"}:
        if not router._transport_user_allowed(event):
            await send_forbidden("You are not allowed to use this bot.")
            return
        if router._totp_enabled(event):
            ok, cmdline = await router.require_totp(event, sink, cmd, cmdline)
            if not ok:
                return
            fields = cmdline.split()
            if not fields:
                return
            rest = cmdline[len(fields[0]) :].strip()
        session = router.current_session_for_user(event.author_id, event.channel_id)
        text = ""
        if cmd == "answer":
            value = rest.strip()
            if not value:
                await send_forbidden("Usage: !c answer [session] -- <text>  or  !c answer <text>")
                return
            if "--" in value:
                left, right = value.split("--", 1)
                if left.strip():
                    session = left.strip()
                text = right.strip()
            else:
                text = value
            if not text:
                await send_forbidden("Answer text required.")
                return
        elif cmd == "approve":
            if rest.strip():
                session = rest.strip()
            text = "yes"
        else:
            if rest.strip():
                session = rest.strip()
            text = "no"
        await router.handle_answer(event, sink, session, text)
        return

    bound_repo = router.get_dm_binding(event)
    if not bound_repo:
        await send(dm_binding_help_text())
        return
    try:
        repo_path = pathutil.resolve_repo_path(router.cfg.codex.code_root, bound_repo)
    except Exception as exc:
        await send_forbidden(f"Repo error: {exc}")
        return
    session = router.current_session_for_user(event.author_id, event.channel_id)
    prefixed_sink = _PrefixedSink(sink, bound_repo)
    if router._totp_enabled(event):
        ok, cmdline = await router.require_totp(event, sink, "resume", cmdline)
        if not ok:
            return
    router.logger.info(
        "dm.prompt",
        extra={"platform": event.platform, "user_id": event.author_id, "repo": bound_repo, "session": session},
    )
    await router.handle_resume(event, prefixed_sink, bound_repo, repo_path, session, cmdline)
