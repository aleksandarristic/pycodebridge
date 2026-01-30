"""Parse Codex `/status` output into structured summaries."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Iterable, Dict, List

@dataclass(frozen=True)
class StatusSummary:
    """Structured summary of key `/status` fields."""

    fields: Dict[str, str]

    def field(self, name: str) -> str | None:
        return self.fields.get(name)

    @property
    def model(self) -> str | None:
        return self.field("Model")

    @property
    def directory(self) -> str | None:
        return self.field("Directory")

    @property
    def context_window(self) -> str | None:
        return self.field("Context window")

    @property
    def five_hour_limit(self) -> str | None:
        return self.field("5h limit")

    @property
    def weekly_limit(self) -> str | None:
        return self.field("Weekly limit")


def parse_status_lines(lines: Iterable[str]) -> StatusSummary:
    """Parse `/status` output into a StatusSummary."""
    parsed: Dict[str, str] = {}
    for raw in lines:
        for line in _expand_status_lines(raw):
            line = line.strip()
            if not line:
                continue
            if line.startswith("╭") or line.startswith("╰"):
                continue
            if line.startswith("│"):  # drop box art
                line = line.strip("│").strip()
            if not line:
                continue
            if line.startswith(">_") or line.startswith("Visit"):
                continue
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            key = key.strip()
            value = value.strip()
            if key and value:
                parsed[key] = value
    return StatusSummary(fields=parsed)


def _expand_status_lines(raw: str) -> List[str]:
    """Return zero or more status lines extracted from raw output."""
    if not raw:
        return []
    line = raw.strip()
    if not line:
        return []
    if not line.startswith("{"):
        return [line]
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        return [line]
    out: List[str] = []
    text = payload.get("text") or payload.get("content") or payload.get("message")
    if isinstance(text, str) and text.strip():
        out.append(text)
    item = payload.get("item") or {}
    if isinstance(item, dict):
        item_text = item.get("text")
        if isinstance(item_text, str) and item_text.strip():
            out.append(item_text)
        for entry in item.get("content", []) or []:
            if not isinstance(entry, dict):
                continue
            entry_text = entry.get("text")
            if isinstance(entry_text, str) and entry_text.strip():
                out.append(entry_text)
    return out or [line]


def format_status_summary(summary: StatusSummary) -> List[str]:
    """Format the parsed summary into chat-appropriate lines."""
    lines: List[str] = []
    for key in ("Model", "Directory", "Context window", "5h limit", "Weekly limit"):
        value = summary.field(key)
        if value:
            lines.append(f"{key}: {value}")
    return lines
