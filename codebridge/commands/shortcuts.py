"""Shortcut normalization for top-level bang command forms."""

from __future__ import annotations

from typing import Iterable, Sequence


def normalize_bang_shortcut(
    content: str,
    known_tokens: Iterable[str],
    *,
    aliases: Sequence[tuple[str, str]] = (),
) -> str:
    """Translate top-level !<command> forms into canonical command text."""
    raw = (content or "").strip()
    if not raw.startswith("!"):
        return ""
    lower = raw.lower()

    # Session-targeted steering/answer shorthands: !s:<session> <text>, !a:<session> <text>
    for token, cmd in (("!s:", "steer"), ("!a:", "answer")):
        if lower.startswith(token):
            after = raw[len(token) :].strip()
            if not after:
                return cmd
            parts = after.split(maxsplit=1)
            session = parts[0].strip()
            text = parts[1].strip() if len(parts) > 1 else ""
            if text:
                return f"{cmd} {session} -- {text}"
            return cmd

    if lower == "!s":
        return "steer"
    if lower.startswith("!s") and len(raw) > len("!s") and raw[len("!s")].isspace():
        return ("steer " + raw[len("!s") :].strip()).strip()
    if lower == "!a":
        return "answer"
    if lower.startswith("!a") and len(raw) > len("!a") and raw[len("!a")].isspace():
        return ("answer " + raw[len("!a") :].strip()).strip()
    if lower in {"!cont", "!continue"}:
        return "choose continue"
    if lower == "!new":
        return "choose new"
    if lower in {"!compact", "!cpt"}:
        return "choose compact"

    for bang, cmd in aliases:
        if lower == bang or lower.startswith(bang + " "):
            tail = raw[len(bang) :].strip()
            return (cmd + " " + tail).strip()

    after_bang = raw[1:].strip()
    if not after_bang:
        return ""
    parts = after_bang.split(maxsplit=1)
    token = parts[0].strip().lower()
    known = {token.lower() for token in known_tokens}
    if token not in known:
        return ""
    tail = parts[1].strip() if len(parts) > 1 else ""
    if tail:
        return f"{token} {tail}"
    return token
