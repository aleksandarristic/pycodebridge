"""Prompt helpers for the DM assistant."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from ..platform.transport import MessageEvent

if TYPE_CHECKING:
    from ..routing.router import Router

DM_ASSISTANT_SESSION = "dm"


def resolve_dm_assistant_repo_path(router: "Router") -> str:
    """Return the managed pycodebridge repo path or raise FileNotFoundError."""
    code_root = Path(router.cfg.codex.code_root)
    candidates = [code_root / "pycodebridge"]
    if code_root.name == "pycodebridge":
        candidates.insert(0, code_root)
    for path in candidates:
        if path.is_dir():
            return str(path)
    raise FileNotFoundError("pycodebridge repo was not found under codex.code_root")


def build_dm_assistant_prompt(router: "Router", event: MessageEvent) -> str:
    """Build the compact start prompt for a DM assistant session."""
    repo_path = resolve_dm_assistant_repo_path(router)
    memory_file = str(router.dm_memory.get_path(event.author_id))
    role = _render_template(
        router.cfg.dm_assistant.start_prompt,
        {
            "REPO_PATH": repo_path,
            "CODE_ROOT": router.cfg.codex.code_root,
            "MEMORY_FILE": memory_file,
            "USER_ID": event.author_id,
        },
    )
    lines = [
        role,
        "",
        "## Key docs",
        "- README.md",
        "- DISCORD.md",
        "- AGENTS.md",
        "- docs/",
        "",
        "## Managed repos",
    ]
    repos = _managed_repo_names(router.cfg.codex.code_root)
    lines.extend(f"- {name}" for name in repos)
    if not repos:
        lines.append("- none")

    lines.extend(["", "## Active sessions"])
    sessions = _session_summary(router)
    lines.extend(f"- {line}" for line in sessions)
    if not sessions:
        lines.append("- none")

    memory = router.dm_memory.read(event.author_id).strip()
    if memory:
        lines.extend(["", "## Your memory for this user:", memory])

    lines.extend(["", "## Memory file", memory_file])
    return "\n".join(lines).strip()


def _render_template(template: str, values: dict[str, str]) -> str:
    rendered = template or ""
    for key, value in values.items():
        rendered = rendered.replace("{{" + key + "}}", value)
    return rendered.strip()


def _managed_repo_names(code_root: str) -> list[str]:
    if not code_root or not os.path.isdir(code_root):
        return []
    names: list[str] = []
    for name in sorted(os.listdir(code_root)):
        path = os.path.join(code_root, name)
        if os.path.isdir(path):
            names.append(name)
        if len(names) >= 20:
            break
    return names


def _session_summary(router: "Router") -> list[str]:
    state = router.state.load()
    lines: list[str] = []
    for channel_id, channel in sorted(state.channels.items()):
        for session_name, session in sorted(channel.sessions.items()):
            backend = session.backend or router.cfg.agent.default_backend or "codex"
            status = "known"
            lines.append(f"{channel_id} -> {session_name}: {session.repo_name} ({backend}, {status})")
            if len(lines) >= 10:
                return lines
    return lines
