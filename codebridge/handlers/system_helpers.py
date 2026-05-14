"""System helper command handlers."""

from __future__ import annotations

import json
import os
import re
import shutil
import asyncio
from typing import TYPE_CHECKING

from ..routing.helpers import HELPER_TIMEOUT, run_limited_command
from ..platform.transport import ResponseSink

if TYPE_CHECKING:
    from ..routing.router import Router

_SEMVER_RE = re.compile(r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?")
_SEMVER_LINE_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")


def _extract_version(text: str) -> str:
    match = _SEMVER_RE.search(text or "")
    if not match:
        return ""
    return match.group(0)


def _extract_line_version(text: str) -> str:
    for line in (text or "").splitlines():
        token = line.strip()
        if _SEMVER_LINE_RE.fullmatch(token):
            return token
    return ""


async def handle_updates(router: "Router", sink: ResponseSink, repo_path: str) -> None:
    """Compare installed Codex CLI version with latest npm release."""
    binary = getattr(router.runner, "binary", "codex") or "codex"
    npm_env = {"PATH": os.environ.get("PATH", ""), "NPM_CONFIG_CACHE": "/tmp/npm-cache"}
    current_task = run_limited_command(
        repo_path,
        [binary, "--version"],
        timeout=HELPER_TIMEOUT,
    )
    latest_task = run_limited_command(repo_path, ["npm", "view", "@openai/codex", "version"], timeout=HELPER_TIMEOUT, env=npm_env)
    (current_out, current_err), (latest_out, latest_err) = await asyncio.gather(current_task, latest_task)
    current = _extract_version(current_out)
    current_raw = (current_out or "").strip() or "(no output)"
    latest = _extract_line_version(latest_out)
    latest_raw = (latest_out or "").strip() or "(no output)"

    if current_err and latest_err:
        await router.reply(
            sink,
            "Could not check updates. Failed to read local Codex version and npm latest version.",
        )
        return

    lines: list[str] = []
    if current:
        lines.append(f"Installed Codex CLI: {current}")
    else:
        lines.append(f"Installed Codex CLI: unknown ({current_raw})")
    if latest:
        lines.append(f"Latest @openai/codex: {latest}")
    else:
        lines.append(f"Latest @openai/codex: unknown ({latest_raw})")

    if current and latest:
        if current == latest:
            lines.append("Status: up to date.")
        else:
            lines.append(f"Status: update available ({current} -> {latest}).")
    elif latest_err:
        lines.append("Status: could not query npm latest version.")
    elif current_err:
        lines.append("Status: could not determine installed Codex version.")
    else:
        lines.append("Status: version comparison unavailable.")

    await router.reply(sink, "\n".join(lines))


async def handle_health(router: "Router", sink: ResponseSink, repo_path: str) -> None:
    """Render runtime diagnostics for operators."""
    binary = getattr(router.runner, "binary", "codex") or "codex"
    resolved_binary = shutil.which(binary)
    current_out, current_err = await run_limited_command(repo_path, [binary, "--version"], timeout=HELPER_TIMEOUT)
    current = _extract_version(current_out)

    snapshots = await router.coordinator.snapshot_all()
    running = sum(1 for statuses in snapshots.values() for st in statuses if st.status == "running")
    queued = sum(1 for statuses in snapshots.values() for st in statuses if st.status == "queued")
    channel_count = len(snapshots)

    state = router.state.load()
    tracked_channels = len(state.channels)
    tracked_sessions = sum(len(ch.sessions) for ch in state.channels.values())

    code_root = router.cfg.codex.code_root or ""
    state_dir = router.cfg.state.data_dir or ""
    log_dir = router.cfg.state.log_dir or ""
    code_root_status = _path_access_status(code_root)
    state_dir_status = _path_access_status(state_dir)
    log_dir_status = _path_access_status(log_dir)
    uid = os.getuid() if hasattr(os, "getuid") else -1
    gid = os.getgid() if hasattr(os, "getgid") else -1

    last_error = _read_last_codex_error_summary(getattr(router, "_codex_error_log_path", ""))
    if not last_error:
        last_error = "none"

    lines = [
        "Health:",
        f"- Codex binary: {binary} ({'found' if resolved_binary else 'not found'})",
        f"- Codex version: {current or 'unknown'}",
        f"- Queue: {running} running, {queued} queued across {channel_count} channel(s)",
        f"- Tracked sessions: {tracked_sessions} across {tracked_channels} channel(s)",
        f"- Last codex error: {last_error}",
        f"- Runtime uid:gid: {uid}:{gid}",
        f"- Env sanity: code_root={code_root_status}, state_dir={state_dir_status}, log_dir={log_dir_status}",
    ]
    if current_err and not current:
        lines.append("- Note: failed to query `codex --version`.")
    await router.reply(sink, "\n".join(lines))


def _path_access_status(path: str) -> str:
    """Return concise path access status for health output."""
    if not path:
        return "missing"
    if not os.path.isdir(path):
        return "missing"
    writable = os.access(path, os.W_OK)
    return "ok(rw)" if writable else "ok(ro)"


def _read_last_codex_error_summary(path: str) -> str:
    """Return a compact summary from the newest codex error log line."""
    if not path or not os.path.exists(path):
        return ""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            lines = fh.readlines()
    except Exception:
        return ""
    for raw in reversed(lines):
        text = (raw or "").strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except Exception:
            continue
        rc = payload.get("return_code")
        note = str(payload.get("note") or "").strip()
        stderr_tail = payload.get("stderr_tail") or []
        tail = ""
        if isinstance(stderr_tail, list) and stderr_tail:
            tail = str(stderr_tail[-1]).strip()
        parts = []
        if rc is not None:
            parts.append(f"rc={rc}")
        if note:
            parts.append(note)
        if tail:
            parts.append(tail)
        summary = " | ".join(p for p in parts if p)
        if summary:
            return summary[:240]
    return ""
