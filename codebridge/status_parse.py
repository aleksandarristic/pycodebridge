"""Parse Codex `/status` output into structured summaries."""

from __future__ import annotations

from dataclasses import dataclass
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
        line = raw.strip()
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


def format_status_summary(summary: StatusSummary) -> List[str]:
    """Format the parsed summary into chat-appropriate lines."""
    lines: List[str] = []
    for key in ("Model", "Directory", "Context window", "5h limit", "Weekly limit"):
        value = summary.field(key)
        if value:
            lines.append(f"{key}: {value}")
    return lines
