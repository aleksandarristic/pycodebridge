"""DM admin command handlers."""

from __future__ import annotations

import os
import time
from typing import TYPE_CHECKING, Awaitable, Callable, Optional

from ..observability.audit import Entry
from ..routing.helpers import (
    DEFAULT_SESSION,
    HELPER_TIMEOUT,
    copy_dir_excluding_git,
    forbidden_message,
    parse_github_clone_url,
    prune_state_for_repo,
    rename_state_repo,
    run_limited_command,
)
from ..sessions.state import utc_now_iso
from ..platform.transport import Capabilities, MessageEvent, ResponseSink
from ..util import path as pathutil

if TYPE_CHECKING:
    from ..routing.router import Router

_DM_COMMAND_ALIASES = {
    "commands": "help",
    "ul": "unlock",
    "lk": "lock",
    "createrepo": "create",
    "new": "create",
    "clonerepo": "clone",
    "copyrepo": "copy",
    "cp": "copy",
    "del": "deleterepo",
    "delete": "deleterepo",
    "ren": "renamerepo",
    "rename": "renamerepo",
    "opts": "options",
}

_DM_SHORTCUT_COMMANDS = {
    "answer",
    "approve",
    "bind",
    "clone",
    "config",
    "copy",
    "create",
    "deleterepo",
    "deny",
    "gh",
    "health",
    "help",
    "lock",
    "options",
    "renamerepo",
    "repo",
    "repos",
    "reset",
    "sessions",
    "status",
    "unbind",
    "unlock",
    "updates",
    "use",
}

_DM_HELP_OVERVIEW_ORDER = (
    "help",
    "bind",
    "use",
    "repo",
    "unbind",
    "status",
    "answer",
    "approve",
    "deny",
    "gh",
    "updates",
    "health",
    "options",
    "unlock",
    "lock",
)

_DM_ADMIN_HELP_OVERVIEW_ORDER = (
    "repos",
    "sessions",
    "config",
    "reset",
    "create",
    "clone",
    "copy",
    "deleterepo",
    "renamerepo",
)

_DM_HELP_DETAILS: dict[str, tuple[str, str]] = {
    "help": ("help [command]", "show DM command help"),
    "bind": ("bind <repo>", "bind this DM to a repo"),
    "use": ("use <repo>", "alias for bind"),
    "repo": ("repo <repo> <prompt>", "run a one-off prompt against a repo"),
    "unbind": ("unbind", "clear bound repo"),
    "status": ("status", "show bound repo and current session"),
    "answer": ("answer [session] -- <text> | answer <text>", "send input to an active Codex session"),
    "approve": ("approve [session]", "send 'yes' to active session"),
    "deny": ("deny [session]", "send 'no' to active session"),
    "gh": ("gh <args>", "run GitHub CLI (bound repo cwd, or code_root if unbound)"),
    "updates": ("updates", "check Codex CLI update status"),
    "health": ("health", "show runtime diagnostics"),
    "options": ("options [show] | options set <name> <value> [local|global]", "show or set runtime options"),
    "unlock": ("unlock/ul [gh|all] [status|ttl]", "unlock command scopes for your account"),
    "lock": ("lock/lk [gh|all]", "clear unlock scopes for your account"),
    "repos": ("repos", "list repos under code_root"),
    "sessions": ("sessions", "list sessions across channels"),
    "config": ("config", "show effective config"),
    "reset": ("reset all", "request reset-all confirmation"),
    "create": ("create/new <name>", "create repo"),
    "clone": ("clone <name> <url>", "clone repo"),
    "copy": ("copy/cp <from> <to>", "copy repo"),
    "deleterepo": ("deleterepo/del <name>", "delete repo"),
    "renamerepo": ("renamerepo/ren <from> <to>", "rename repo"),
}


def _dm_shortcut_cmdline(content: str) -> str:
    """Translate DM-only top-level shortcuts into canonical command text."""
    raw = (content or "").strip()
    if not raw.startswith("!"):
        return ""
    lower = raw.lower()

    def _tail(prefix: str) -> str:
        return raw[len(prefix) :].strip()

    dm_mapping = (
        ("!commands", "help"),
        ("!repos", "repos"),
        ("!sessions", "sessions"),
        ("!status", "status"),
        ("!config", "config"),
        ("!updates", "updates"),
        ("!create", "create"),
        ("!new", "create"),
        ("!createrepo", "create"),
        ("!clone", "clone"),
        ("!clonerepo", "clone"),
        ("!copy", "copy"),
        ("!cp", "copy"),
        ("!copyrepo", "copy"),
        ("!deleterepo", "deleterepo"),
        ("!delete", "deleterepo"),
        ("!del", "deleterepo"),
        ("!renamerepo", "renamerepo"),
        ("!rename", "renamerepo"),
        ("!ren", "renamerepo"),
        ("!reset", "reset"),
        ("!lk", "lock"),
        ("!bind", "bind"),
        ("!use", "use"),
        ("!repo", "repo"),
        ("!unbind", "unbind"),
        ("!answer", "answer"),
        ("!reply", "answer"),
        ("!approve", "approve"),
        ("!deny", "deny"),
    )
    for bang, cmd in dm_mapping:
        if lower == bang or lower.startswith(bang + " "):
            return (cmd + " " + _tail(bang)).strip()
    return ""


def _normalize_dm_help_token(token: str) -> str:
    raw = (token or "").strip().lower()
    if not raw:
        return ""
    if raw == "commands":
        return "help"
    return _DM_COMMAND_ALIASES.get(raw, raw)


def _render_dm_help_index(prefix: str, is_admin: bool) -> str:
    lines = [
        "DM Commands:",
        "",
        "Repo-bound / session controls:",
    ]
    for cmd in _DM_HELP_OVERVIEW_ORDER:
        usage, desc = _DM_HELP_DETAILS[cmd]
        lines.append(f"- `{prefix} {usage}` - {desc}")
    if is_admin:
        lines.extend(["", "DM admin-only commands:"])
        for cmd in _DM_ADMIN_HELP_OVERVIEW_ORDER:
            usage, desc = _DM_HELP_DETAILS[cmd]
            lines.append(f"- `{prefix} {usage}` - {desc}")
    return "\n".join(lines)


def _render_dm_help_command(prefix: str, cmd: str, is_admin: bool) -> str | None:
    allowed = set(_DM_HELP_OVERVIEW_ORDER)
    if is_admin:
        allowed.update(_DM_ADMIN_HELP_OVERVIEW_ORDER)
    if cmd not in allowed:
        return None
    usage, desc = _DM_HELP_DETAILS[cmd]
    return f"DM help `{cmd}`:\n- Usage: `{prefix} {usage}`\n- {desc}"


def _require_dangerous_confirmation_token(router: "Router", rest: str) -> tuple[bool, str]:
    """Validate dangerous-operation confirmation token in arg text."""
    token = (router.cfg.git.dangerous_confirmation_token or "--confirm-dangerous").strip() or "--confirm-dangerous"
    args = (rest or "").split()
    if token in args:
        filtered = " ".join(a for a in args if a != token).strip()
        return True, filtered
    return False, rest


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
        "help — show this help [open]\n"
        "repos — list repos under code_root [open]\n"
        "sessions — list sessions across channels [open]\n"
        "status — show queues and running jobs [open]\n"
        "config — show effective config [open]\n"
        "options [show] | options set <name> <value> [local|global] — runtime options (set requires totp unless unlocked) [mixed]\n"
        "gh <args> — run GitHub CLI in DM context [unlock/gh]\n"
        "updates — check Codex CLI update status [open]\n"
        "create/new <name> — create repo [totp]\n"
        "clone <name> <url> — clone repo [totp]\n"
        "copy/cp <from> <to> — copy repo [totp]\n"
        "deleterepo/del <name> — delete repo [totp]\n"
        "renamerepo/ren <from> <to> — rename repo [totp]\n"
        "reset all — request reset-all confirmation; next reply must be `yes` within 60s [open]\n"
        "unlock/ul [gh|all] [status|ttl] — unlock command scopes for your account [totp; status=open]\n"
        "lock/lk [gh|all] — clear unlock scopes for your account [open]\n"
    )


def dm_binding_help_text() -> str:
    """Return DM repo binding help text."""
    return (
        "DM Repo Binding:\n"
        "bind <repo> — bind this DM to a repo [unlock/default]\n"
        "use <repo> — alias for bind [unlock/default]\n"
        "repo <repo> <prompt> — run a one-off prompt against a repo [unlock/default]\n"
        "gh <args> — run GitHub CLI (bound repo cwd, or code_root if unbound) [unlock/gh]\n"
        "updates — check Codex CLI update status [open]\n"
        "options [show] | options set <name> <value> [local|global] — runtime options (set requires totp unless unlocked) [mixed]\n"
        "unlock/ul [gh|all] [status|ttl] — unlock command scopes for your account [totp; status=open]\n"
        "lock/lk [gh|all] — clear unlock scopes for your account [open]\n"
        "unbind — clear bound repo [unlock/default]\n"
        "status — show current bound repo and session [open]\n"
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
    await router.bootstrap_repo_git_config(repo_path)
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
    await router.bootstrap_repo_git_config(repo_path)
    await dm_reply(router, sink, entry, f"Clone complete: {clone_url} -> {repo_path}. Use `#codex-{repo_name}` for prompts.")
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
    await router.bootstrap_repo_git_config(dst_path)
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


def _is_dm_admin(router: "Router", event: MessageEvent) -> bool:
    return event.platform == "discord" and router.cfg.discord.dm_admin_enabled and router._dm_admin_allowed(event.author_id)


async def _prepare_dm_content(
    router: "Router",
    event: MessageEvent,
    sink: ResponseSink,
    content: str,
    prefix: str,
) -> tuple[str, bool]:
    """Apply DM shortcuts and handle pending upload path prompts."""
    shortcut_cmdline = router._shortcut_cmdline(content)
    if not shortcut_cmdline:
        shortcut_cmdline = _dm_shortcut_cmdline(content)
    if shortcut_cmdline:
        shortcut_head = shortcut_cmdline.split(maxsplit=1)[0].lower()
        if shortcut_head in _DM_SHORTCUT_COMMANDS:
            content = f"{prefix} {shortcut_cmdline}".strip()
    pending_upload = False
    file_transfers = getattr(router, "file_transfers", None)
    if file_transfers is not None and hasattr(file_transfers, "has_pending_upload"):
        pending_upload = file_transfers.has_pending_upload(event)
    pending_content = content
    if pending_upload and router._totp_enabled(event):
        ok, pending_content = await router.require_totp(event, sink, "upload", content)
        if not ok:
            return content, True
    if await router.handle_pending_upload_response(event, sink, router.get_dm_binding(event) or "", pending_content):
        return pending_content, True
    return content, False


async def _handle_dm_unprefixed(
    router: "Router",
    event: MessageEvent,
    sink: ResponseSink,
    content: str,
    prefix: str,
) -> bool:
    """Handle unprefixed DM input (relay/bound repo prompts/uploads)."""
    if content.startswith(prefix):
        return False
    if not router._transport_user_allowed(event):
        await sink.send(forbidden_message("You are not allowed to use this bot."))
        return True
    relay_session, ambiguous = await router.pending_input_session(event)
    if ambiguous:
        await sink.send(forbidden_message("Multiple sessions are waiting for input. Use `!c answer <session> -- <text>`."))
        return True
    if relay_session and not event.attachments:
        relay_text = content.strip()
        if not relay_text:
            return True
        if router._totp_enabled(event) and not router._totp_is_unlocked(event):
            ok, relay_text = await router.require_totp(event, sink, "answer", relay_text)
            if not ok:
                return True
        await router.handle_answer(event, sink, relay_session, relay_text)
        return True
    bound_repo = router.get_dm_binding(event)
    if not bound_repo:
        await sink.send("No repo bound. Send `!c repos` to list and then `!c bind <repo>` to bind a repo. Send `!c help` for instructions.")
        return True
    try:
        repo_path = pathutil.resolve_repo_path(router.cfg.codex.code_root, bound_repo)
    except Exception as exc:
        await sink.send(forbidden_message(f"Repo error: {exc}"))
        return True
    if event.attachments:
        if router._totp_enabled(event):
            ok, _ = await router.require_totp(event, sink, "upload", content)
            if not ok:
                return True
        await router.handle_upload_request(event, sink, bound_repo, repo_path)
        return True
    session = router.current_session_for_user(event.author_id, event.channel_id)
    prefixed_sink = _PrefixedSink(sink, bound_repo)
    if router._totp_enabled(event) and not router._totp_is_unlocked(event):
        ok, content = await router.require_totp(event, sink, "resume", content)
        if not ok:
            return True
    await router.handle_resume(event, prefixed_sink, bound_repo, repo_path, session, content)
    return True


async def _dispatch_prefixed_dm_command(
    router: "Router",
    event: MessageEvent,
    sink: ResponseSink,
    entry: Optional[Entry],
    prefix: str,
    cmd: str,
    rest: str,
    cmdline: str,
    is_admin: bool,
    send: Callable[[str], Awaitable[None]],
    send_forbidden: Callable[[str], Awaitable[None]],
) -> None:
    """Dispatch a parsed prefixed DM command and perform fallback handling."""
    binding_commands = {"bind", "use", "repo", "unbind", "status", "unlock", "lock", "updates", "health", "options"}
    admin_commands = {
        "repos",
        "sessions",
        "config",
        "reset",
        "create",
        "clone",
        "copy",
        "deleterepo",
        "renamerepo",
    }

    if cmd == "help":
        if not (router._transport_user_allowed(event) or is_admin):
            await send_forbidden("You are not allowed to use this bot.")
            return
        token = _normalize_dm_help_token(rest)
        if not token:
            await send(_render_dm_help_index(prefix, is_admin))
            return
        detail = _render_dm_help_command(prefix, token, is_admin)
        if not detail:
            unknown = token or rest.strip()
            await send_forbidden(f"Unknown DM command `{unknown}`. Use `{prefix} help` to list DM commands.")
            return
        await send(detail)
        return

    if cmd in admin_commands:
        if not is_admin:
            await send_forbidden("You are not allowed to use DM admin commands.")
            return
        if cmd in {"create", "clone", "copy", "deleterepo", "renamerepo"}:
            ok, cmdline = await router.require_totp(event, sink, cmd, cmdline)
            if not ok:
                return
            fields = cmdline.split()
            if not fields:
                return
            cmd = _DM_COMMAND_ALIASES.get(fields[0].lower(), fields[0].lower())
            rest = cmdline[len(fields[0]) :].strip()
        router.logger.info(
            "dm.admin",
            extra={"platform": event.platform, "user_id": event.author_id, "cmd": cmd},
        )
        if cmd == "repos":
            msg = await dm_list_repos(router)
            await send(msg)
            return
        if cmd == "sessions":
            msg = await dm_list_sessions(router)
            await send(msg)
            return
        if cmd == "config":
            if rest.strip():
                await send_forbidden(
                    "Unknown `config` subcommand. Use `!cfg` to show effective config, "
                    "or `!opts set <key> <value> [local|global]` to update runtime options."
                )
                return
            await send(router.config_text())
            return
        if cmd == "reset":
            token = rest.strip().lower()
            if token == "all":
                ttl = router.begin_reset_all_confirmation(event)
                await send(
                    f"Are you sure you want to reset all sessions across all channels? "
                    f"This will clear stored context, cancel queued jobs, and stop active work where possible. "
                    f"Reply with `yes` within {ttl}s to proceed. "
                    f"Any other reply cancels immediately; no reply before timeout expires the confirmation."
                )
                return
            await send_forbidden("Usage: !c reset all")
            return
        if cmd == "create":
            name = rest.strip()
            if not name:
                await send_forbidden("Usage: !c create <name>")
                return
            err = await dm_create_repo(router, event, sink, name, entry)
            if err:
                await send_forbidden(str(err))
            return
        if cmd == "clone":
            parts = rest.split(maxsplit=1)
            if len(parts) < 2:
                await send_forbidden("Usage: !c clone <name> <url>")
                return
            err = await dm_clone_repo(router, event, sink, parts[0], parts[1], entry)
            if err:
                await send_forbidden(str(err))
            return
        if cmd == "copy":
            parts = rest.split(maxsplit=1)
            if len(parts) < 2:
                await send_forbidden("Usage: !c copy <from> <to>")
                return
            err = await dm_copy_repo(router, event, sink, parts[0], parts[1], entry)
            if err:
                await send_forbidden(str(err))
            return
        if cmd == "deleterepo":
            ok_confirm, rest = _require_dangerous_confirmation_token(router, rest)
            if not ok_confirm:
                token = (router.cfg.git.dangerous_confirmation_token or "--confirm-dangerous").strip() or "--confirm-dangerous"
                await send_forbidden(f"Dangerous operation detected (delete repo). Re-run with `{token}` to confirm.")
                return
            name = rest.strip()
            if not name:
                await send_forbidden("Usage: !c deleterepo <name>")
                return
            err = await dm_delete_repo(router, event, sink, name, entry)
            if err:
                await send_forbidden(str(err))
            return
        if cmd == "renamerepo":
            ok_confirm, rest = _require_dangerous_confirmation_token(router, rest)
            if not ok_confirm:
                token = (router.cfg.git.dangerous_confirmation_token or "--confirm-dangerous").strip() or "--confirm-dangerous"
                await send_forbidden(f"Dangerous operation detected (rename repo). Re-run with `{token}` to confirm.")
                return
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
        if router._totp_enabled(event) and router._totp_required_for_command(event, cmd, rest):
            ok, cmdline = await router.require_totp(event, sink, cmd, cmdline)
            if not ok:
                return
            fields = cmdline.split()
            if not fields:
                return
            cmd = _DM_COMMAND_ALIASES.get(fields[0].lower(), fields[0].lower())
            rest = cmdline[len(fields[0]) :].strip()
        if cmd == "unlock":
            await router.handle_unlock(event, sink, rest)
            return
        if cmd == "lock":
            await router.handle_lock(event, sink, rest)
            return
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
        if cmd == "updates":
            run_path = router.cfg.codex.code_root
            bound = router.get_dm_binding(event)
            if bound:
                try:
                    run_path = pathutil.resolve_repo_path(router.cfg.codex.code_root, bound)
                except Exception as exc:
                    await send_forbidden(f"Repo error: {exc}")
                    return
            await router.handle_updates(sink, run_path)
            return
        if cmd == "health":
            run_path = router.cfg.codex.code_root
            bound = router.get_dm_binding(event)
            if bound:
                try:
                    run_path = pathutil.resolve_repo_path(router.cfg.codex.code_root, bound)
                except Exception as exc:
                    await send_forbidden(f"Repo error: {exc}")
                    return
            await router.handle_health(sink, run_path)
            return
        if cmd == "options":
            await router.handle_options(event, sink, rest)
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
        if router._totp_enabled(event) and not router._totp_is_unlocked(event, "gh"):
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
        if router._totp_enabled(event) and not router._totp_is_unlocked(event):
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
    if router._totp_enabled(event) and not router._totp_is_unlocked(event):
        ok, cmdline = await router.require_totp(event, sink, "resume", cmdline)
        if not ok:
            return
    router.logger.info(
        "dm.prompt",
        extra={"platform": event.platform, "user_id": event.author_id, "repo": bound_repo, "session": session},
    )
    await router.handle_resume(event, prefixed_sink, bound_repo, repo_path, session, cmdline)


async def handle_dm_message(router: "Router", event: MessageEvent, sink: ResponseSink) -> None:
    """Handle an incoming DM admin message."""
    content = (event.content or "").strip()
    prefix = router._transport_prefix(event)
    content, handled = await _prepare_dm_content(router, event, sink, content, prefix)
    if handled:
        return

    if _is_dm_admin(router, event) and router.has_reset_all_confirmation_pending(event):
        answer = (content or "").strip().lower()
        if answer in {"yes", "y"}:
            if not router.consume_reset_all_confirmation(event):
                await sink.send("Reset-all confirmation expired. Run `!c reset all` again.")
                return
            await router.handle_reset_all_sessions(sink)
            return
        router.clear_reset_all_confirmation(event)
        await sink.send("Reset-all operation cancelled.")
        return

    if await _handle_dm_unprefixed(router, event, sink, content, prefix):
        return

    cmdline = content[len(prefix) :].strip()
    if not cmdline:
        return
    cmdline = router._normalize_unlock_totp_syntax(cmdline)
    fields = cmdline.split()
    cmd = _DM_COMMAND_ALIASES.get(fields[0].lower(), fields[0].lower())
    rest = cmdline[len(fields[0]) :].strip()

    entry = dm_audit_start(router, event, cmd, rest)

    async def send(text: str) -> None:
        await dm_reply(router, sink, entry, text)

    async def send_forbidden(detail: str) -> None:
        await dm_reply(router, sink, entry, forbidden_message(detail))

    await _dispatch_prefixed_dm_command(
        router,
        event,
        sink,
        entry,
        prefix,
        cmd,
        rest,
        cmdline,
        _is_dm_admin(router, event),
        send,
        send_forbidden,
    )
