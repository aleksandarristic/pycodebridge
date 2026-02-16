"""Shared helper functions and constants for the router."""

from __future__ import annotations

import asyncio
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Tuple

from .codex import Event
from .util import path as pathutil

FORBIDDEN_PREFIX = "I'm sorry, Dave. I'm afraid I can't do that."
DEFAULT_SESSION = "default"
MAX_SESSIONS_PER_CHANNEL = 3
SESSION_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

HELPER_TIMEOUT = 30.0
TESTS_TIMEOUT = 120.0
HELPER_OUTPUT_LIMIT = 128 * 1024
UPLOAD_TIMEOUT = 60.0
UPLOAD_TTL_SECONDS = 300


@dataclass
class PendingConflict:
    """Pending conflict for start vs existing session."""
    repo_name: str
    session: str
    thread_id: str
    user_id: str
    expires_at: float


@dataclass
class UsageStats:
    """Token usage counters per session."""
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


@dataclass
class PendingUpload:
    """Pending upload state for attachments."""
    repo_name: str
    repo_path: str
    attachments: list[Any]
    user_id: str
    created_at: float
    expires_at: float


def forbidden_message(detail: str) -> str:
    """Format a standard forbidden response message."""
    return f"{FORBIDDEN_PREFIX}\n```text\n{detail}\n```"


def normalize_session(name: str) -> str:
    """Normalize and validate session name input."""
    if not name:
        return DEFAULT_SESSION
    if not SESSION_RE.match(name):
        raise ValueError("Invalid session name. Use 1-64 characters: letters, numbers, . _ -")
    return name


def pending_key(channel_id: str, session: str) -> str:
    """Build a stable key for pending conflicts."""
    return f"{channel_id}:{session or DEFAULT_SESSION}"


def has_forbidden_flags(args: list[str]) -> bool:
    """Return True if args include disallowed flags."""
    for a in args:
        if a in {"-f", "--force", "--force-with-lease", "--rebase", "--squash"}:
            return True
    return False


def find_unsafe_git_flag(args: list[str]) -> Optional[str]:
    """Return the first unsafe git flag, if any."""
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
    """Convert Codex usage event into UsageStats."""
    if not evt.usage:
        return None
    usage = evt.usage or {}
    return UsageStats(
        input_tokens=int(usage.get("input_tokens") or usage.get("inputTokens") or 0),
        output_tokens=int(usage.get("output_tokens") or usage.get("outputTokens") or 0),
        total_tokens=int(usage.get("total_tokens") or usage.get("totalTokens") or 0),
    )


def count_active_sessions(state, channel_id: str) -> int:
    """Count sessions for a channel in state."""
    ch = state.channels.get(channel_id)
    if not ch:
        return 0
    return len(ch.sessions)


def session_exists(state, channel_id: str, session: str) -> bool:
    """Return True if a session exists for the channel."""
    ch = state.channels.get(channel_id)
    if not ch:
        return False
    return session in ch.sessions


def existing_thread(state, channel_id: str, session: str) -> str:
    """Return the thread id for a session, if any."""
    ch = state.channels.get(channel_id)
    if not ch:
        return ""
    sess = ch.sessions.get(session or DEFAULT_SESSION)
    if not sess:
        return ""
    return sess.thread_id


def set_sticky(fs, channel_id: str, user_id: str, session: str) -> None:
    """Set sticky session selection for a user in state."""
    ch = fs.channels.get(channel_id)
    if ch is None:
        from .state import ChannelState

        ch = ChannelState()
    if ch.sticky is None:
        ch.sticky = {}
    ch.sticky[user_id] = session
    fs.channels[channel_id] = ch


def prune_state_for_repo(fs, repo_name: str, repo_path: str) -> None:
    """Remove state entries referencing a repo."""
    repo_key = _repo_key(repo_name)
    for channel_id, ch in list(fs.channels.items()):
        changed = False
        for sess_name, sess in list(ch.sessions.items()):
            if _repo_key(sess.repo_name) == repo_key or sess.repo_path == repo_path:
                del ch.sessions[sess_name]
                changed = True
        if changed:
            for user_id, sess_name in list(ch.sticky.items()):
                if sess_name not in ch.sessions:
                    del ch.sticky[user_id]
            if not ch.sessions and not ch.sticky:
                del fs.channels[channel_id]
            else:
                fs.channels[channel_id] = ch


def rename_state_repo(fs, from_name: str, from_path: str, to_name: str, to_path: str) -> None:
    """Update state entries after a repo rename."""
    from_key = _repo_key(from_name)
    for channel_id, ch in fs.channels.items():
        changed = False
        for sess_name, sess in ch.sessions.items():
            if _repo_key(sess.repo_name) == from_key or sess.repo_path == from_path:
                sess.repo_name = to_name
                sess.repo_path = to_path
                changed = True
        if changed:
            fs.channels[channel_id] = ch


def _repo_key(repo_name: str) -> str:
    raw = (repo_name or "").strip()
    if not raw:
        return ""
    try:
        return pathutil.normalize_repo_name(raw)
    except ValueError:
        return raw.lower()


def build_tree(repo_path: str, max_depth: int = 3) -> str:
    """Build a pruned repo tree listing."""
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


def parse_github_clone_url(raw: str) -> str:
    """Normalize GitHub clone URL inputs."""
    raw = raw.strip()
    if not raw:
        raise ValueError("GitHub URL required")
    if raw.startswith("git@github.com:"):
        path = raw.replace("git@github.com:", "", 1)
        return normalize_github_path(path)
    if raw.startswith("github.com/") or raw.startswith("www.github.com/"):
        raw = "https://" + raw
    if raw.startswith("https://github.com/") or raw.startswith("https://www.github.com/"):
        path = raw.split("github.com/", 1)[1]
        return normalize_github_path(path)
    raise ValueError("Only github.com URLs are supported")


def normalize_github_path(path: str) -> str:
    """Normalize a GitHub path to an HTTPS clone URL."""
    path = path.strip().strip("/")
    if path.endswith(".git"):
        path = path[: -len(".git")]
    parts = path.split("/")
    if len(parts) < 2 or not parts[0] or not parts[1]:
        raise ValueError("Invalid GitHub repo path")
    owner = parts[0]
    repo = parts[1]
    return f"https://github.com/{owner}/{repo}.git"


def copy_dir_excluding_git(src: str, dst: str) -> None:
    """Copy a directory excluding .git."""
    if not os.path.isdir(src):
        raise ValueError("source is not a directory")
    os.makedirs(dst, exist_ok=True)
    for root, dirs, files in os.walk(src):
        rel = os.path.relpath(root, src)
        if rel == ".git" or rel.startswith(".git" + os.sep):
            dirs[:] = []
            continue
        if ".git" in dirs:
            dirs.remove(".git")
        target_dir = dst if rel == "." else os.path.join(dst, rel)
        os.makedirs(target_dir, exist_ok=True)
        for name in files:
            src_path = os.path.join(root, name)
            dst_path = os.path.join(target_dir, name)
            if os.path.islink(src_path):
                continue
            copy_file(src_path, dst_path)


def copy_file(src: str, dst: str) -> None:
    """Copy a file to a destination path, creating directories."""
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(src, "rb") as fsrc:
        data = fsrc.read()
    with open(dst, "wb") as fdst:
        fdst.write(data)


def trim_output(text: str, max_lines: int, max_bytes: int) -> str:
    """Trim output by line and byte limits for Discord safety."""
    lines = text.split("\n")
    if len(lines) > max_lines:
        lines = lines[:max_lines] + ["...(truncated)"]
    joined = "\n".join(lines)
    if len(joined) > max_bytes:
        joined = joined[:max_bytes] + "\n...(truncated)"
    return joined


async def run_limited_command(repo_path: str, args: list[str], timeout: float = HELPER_TIMEOUT) -> Tuple[str, Optional[Exception]]:
    """Run a helper command with time/output limits."""
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
