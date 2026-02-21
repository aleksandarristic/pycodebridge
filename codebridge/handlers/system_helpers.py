"""System helper command handlers."""

from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING

from ..router_helpers import HELPER_TIMEOUT, run_limited_command
from ..transport import ResponseSink

if TYPE_CHECKING:
    from ..router import Router

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
    current_out, current_err = await run_limited_command(
        repo_path,
        [binary, "--version"],
        timeout=HELPER_TIMEOUT,
    )
    current = _extract_version(current_out)
    current_raw = (current_out or "").strip() or "(no output)"

    npm_env = os.environ.copy()
    npm_env.setdefault("NPM_CONFIG_CACHE", "/tmp/npm-cache")
    latest_out, latest_err = await run_limited_command(
        repo_path,
        ["npm", "view", "@openai/codex", "version"],
        timeout=HELPER_TIMEOUT,
        env=npm_env,
    )
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
