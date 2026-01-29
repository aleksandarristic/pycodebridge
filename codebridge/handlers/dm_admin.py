"""DM admin command handlers."""

from __future__ import annotations

import os
import time
from typing import TYPE_CHECKING, Optional

import discord

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
from ..util import path as pathutil

if TYPE_CHECKING:
    from ..router import Router


def dm_help_text() -> str:
    """Return DM admin help text."""
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


async def dm_reply(router: "Router", channel: discord.abc.Messageable, entry: Optional[Entry], msg: str) -> None:
    """Send a DM reply and record it to audit logs."""
    router.append_audit_discord(entry, msg)
    await channel.send(msg)


def dm_audit_start(router: "Router", message: discord.Message, cmd: str, rest: str) -> Optional[Entry]:
    """Start a DM audit entry for admin commands."""
    meta = {
        "command": cmd,
        "args": rest,
        "timestamp": utc_now_iso(),
        "channel": f"dm-{message.author.id}",
    }
    return router.audit_start(f"dm-{message.author.id}", "admin", "dm", meta)


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
    snapshots = await router.queue.snapshot_all()
    lines = []
    for channel_id, statuses in snapshots.items():
        for st in statuses:
            lines.append(f"{channel_id}: {st.job_id} [{st.status}] session:{st.session or DEFAULT_SESSION} pos:{st.position}")
    return "\n".join(lines) if lines else "No queued or running jobs."


async def dm_create_repo(router: "Router", message: discord.Message, repo_name: str, entry: Optional[Entry]) -> Optional[Exception]:
    """Create a new repo via DM admin command."""
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
    await dm_reply(router, message.channel, entry, f"Created repo at {repo_path}. Continue in #codex-{repo_name}")
    router.logger.info("dm.createrepo.ok", extra={"user_id": str(message.author.id), "repo": repo_name, "path": repo_path})
    return None


async def dm_clone_repo(router: "Router", message: discord.Message, repo_name: str, raw_url: str, entry: Optional[Entry]) -> Optional[Exception]:
    """Clone a repo via DM admin command."""
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
    await dm_reply(router, message.channel, entry, f"Cloned {clone_url} into {repo_path}. Continue in #codex-{repo_name}")
    router.logger.info("dm.clonerepo.ok", extra={"user_id": str(message.author.id), "repo": repo_name, "url": clone_url, "path": repo_path})
    return None


async def dm_copy_repo(router: "Router", message: discord.Message, from_name: str, to_name: str, entry: Optional[Entry]) -> Optional[Exception]:
    """Copy a repo via DM admin command."""
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
    await dm_reply(router, message.channel, entry, f"Copied repo to {dst_path}. Continue in #codex-{to_name}")
    router.logger.info("dm.copyrepo.ok", extra={"user_id": str(message.author.id), "repo": from_name, "target": dst_path})
    return None


async def dm_delete_repo(router: "Router", message: discord.Message, repo_name: str, entry: Optional[Entry]) -> Optional[Exception]:
    """Delete a repo via DM admin command."""
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
    await dm_reply(router, message.channel, entry, f"Deleted repo {repo_name}")
    router.logger.info("dm.deleterepo.ok", extra={"user_id": str(message.author.id), "repo": repo_name})
    return None


async def dm_rename_repo(router: "Router", message: discord.Message, from_name: str, to_name: str, entry: Optional[Entry]) -> Optional[Exception]:
    """Rename a repo via DM admin command."""
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
    await dm_reply(router, message.channel, entry, f"Renamed repo {from_name} to {to_name}. Continue in #codex-{to_name}")
    router.logger.info("dm.renamerepo.ok", extra={"user_id": str(message.author.id), "repo": from_name, "target": dst_path})
    return None


async def handle_dm_message(router: "Router", message: discord.Message) -> None:
    """Handle an incoming DM admin message."""
    content = (message.content or "").strip()
    if not content.startswith(router.cfg.discord.prefix or "!c"):
        return
    cmdline = content[len(router.cfg.discord.prefix or "!c") :].strip()
    if not cmdline:
        return
    fields = cmdline.split()
    cmd = fields[0].lower()
    rest = cmdline[len(fields[0]) :].strip()

    entry = dm_audit_start(router, message, cmd, rest)

    async def send(text: str) -> None:
        await dm_reply(router, message.channel, entry, text)

    async def send_forbidden(detail: str) -> None:
        await dm_reply(router, message.channel, entry, forbidden_message(detail))

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
    if cmd == "status":
        await send(await dm_status(router))
        return
    if cmd == "config":
        await send(router.config_text())
        return
    if cmd == "createrepo":
        name = rest.strip()
        if not name:
            await send_forbidden("Usage: !c createrepo <name>")
            return
        err = await dm_create_repo(router, message, name, entry)
        if err:
            await send_forbidden(str(err))
        return
    if cmd == "clonerepo":
        parts = rest.split(maxsplit=1)
        if len(parts) < 2:
            await send_forbidden("Usage: !c clonerepo <name> <url>")
            return
        err = await dm_clone_repo(router, message, parts[0], parts[1], entry)
        if err:
            await send_forbidden(str(err))
        return
    if cmd == "copyrepo":
        parts = rest.split(maxsplit=1)
        if len(parts) < 2:
            await send_forbidden("Usage: !c copyrepo <from> <to>")
            return
        err = await dm_copy_repo(router, message, parts[0], parts[1], entry)
        if err:
            await send_forbidden(str(err))
        return
    if cmd in {"deleterepo", "delete"}:
        name = rest.strip()
        if not name:
            await send_forbidden("Usage: !c deleterepo <name>")
            return
        err = await dm_delete_repo(router, message, name, entry)
        if err:
            await send_forbidden(str(err))
        return
    if cmd in {"renamerepo", "rename"}:
        parts = rest.split(maxsplit=1)
        if len(parts) < 2:
            await send_forbidden("Usage: !c renamerepo <from> <to>")
            return
        err = await dm_rename_repo(router, message, parts[0], parts[1], entry)
        if err:
            await send_forbidden(str(err))
        return

    await send_forbidden("Unknown DM command. Try !c help.")
