"""Parse @agent mentions from dispatch messages."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

KNOWN_AGENTS: frozenset[str] = frozenset({"codex", "claude", "gemini"})

_MENTION_RE = re.compile(r"(?<![A-Za-z0-9._-])@([A-Za-z]+)\b(?![A-Za-z0-9._-])")
_WHITESPACE_RE = re.compile(r"\s+")


@dataclass
class DispatchSpec:
    """Result of parsing a multi-agent dispatch message."""
    agents: List[str]        # ordered, deduplicated, lowercase agent names
    prompt: str              # message with known @agent mentions stripped
    is_orchestrated: bool    # True when claude leads other agents
    is_fanout: bool          # True when more than one agent
    raw: str                 # original message unchanged


def parse_dispatch(message: str) -> Optional[DispatchSpec]:
    """Return a DispatchSpec if the message contains @agent mentions, else None.

    Rules:
    - @claude + other agents → is_orchestrated=True, is_fanout=True
    - Multiple non-claude agents → is_fanout=True
    - Single agent → solo dispatch
    - No known @mentions → return None
    """
    raw = message or ""
    tokens = _MENTION_RE.findall(raw)

    seen: set[str] = set()
    agents: List[str] = []
    for token in tokens:
        lower = token.lower()
        if lower in KNOWN_AGENTS and lower not in seen:
            seen.add(lower)
            agents.append(lower)

    if not agents:
        return None

    prompt = _strip_known_mentions(raw)
    is_orchestrated = "claude" in agents and len(agents) > 1
    is_fanout = len(agents) > 1

    return DispatchSpec(
        agents=agents,
        prompt=prompt,
        is_orchestrated=is_orchestrated,
        is_fanout=is_fanout,
        raw=raw,
    )


def _strip_known_mentions(text: str) -> str:
    """Remove known @agent mentions and normalise whitespace."""
    result = _MENTION_RE.sub(
        lambda m: "" if m.group(1).lower() in KNOWN_AGENTS else m.group(0),
        text,
    )
    return _WHITESPACE_RE.sub(" ", result).strip()
