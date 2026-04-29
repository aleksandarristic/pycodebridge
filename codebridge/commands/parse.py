"""Command parsing helpers for Discord/Codex CLI commands."""

from __future__ import annotations


def parse_session_and_prompt(rest: str) -> tuple[str, str]:
    """Parse an optional session name and prompt string from a command tail."""
    rest = rest.strip()
    if not rest:
        return "default", ""
    fields = rest.split()
    session = fields[0]
    prompt = rest[len(session) :].strip()
    return session, prompt


def parse_choose(rest: str) -> tuple[str, str]:
    """Parse a choose command into (choice, session)."""
    valid = {"resume", "replace", "continue", "cont", "new", "start", "compact", "summary"}
    parts = rest.split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    if len(parts) >= 2 and parts[1].lower() in valid:
        return parts[1], parts[0]
    return parts[0], ""


def parse_session_or_limit(rest: str) -> tuple[str, int]:
    """Parse either a session name or numeric limit from a command tail."""
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


def parse_session_and_id(rest: str) -> tuple[str, str]:
    """Parse a session name and identifier from a command tail."""
    rest = rest.strip()
    if not rest:
        return "", ""
    parts = rest.split()
    if len(parts) == 1:
        return "", parts[0]
    return parts[0], parts[1]


def parse_log_count(args: list[str]) -> int:
    """Parse a bounded log count from command args."""
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


def parse_session_quit_alias(fields: list[str]) -> str:
    """Parse `<session> /quit` shorthand and return the session token."""
    if len(fields) >= 2 and fields[1] == "/quit":
        return fields[0]
    return ""


def parse_session_slash_prompt(cmdline: str) -> tuple[str, str]:
    """Parse slash-style prompt forms.

    Returns `(session, prompt)` where session is empty when no slash form matches.
    """
    raw = (cmdline or "").strip()
    if not raw:
        return "", ""
    if raw.startswith("/"):
        return "default", raw
    fields = raw.split()
    if len(fields) >= 2 and fields[1].startswith("/"):
        session = fields[0]
        prompt = raw[len(fields[0]) :].strip()
        return session, prompt
    return "", ""
