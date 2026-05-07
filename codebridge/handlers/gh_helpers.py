"""GitHub CLI helper command handlers."""

from __future__ import annotations

import shlex
from typing import TYPE_CHECKING

from ..routing.helpers import run_limited_command, trim_output
from ..platform.transport import ResponseSink
from ..util.ansi import strip_control_codes
from ..util import path as pathutil

if TYPE_CHECKING:
    from ..routing.router import Router


async def handle_gh(router: "Router", sink: ResponseSink, repo_path: str, rest: str) -> None:
    """Run gh helper commands directly in the repo directory."""
    fields = shlex.split(rest) if rest else []
    if not fields:
        await router.reply(sink, "Usage: !c gh <args> (example: !c gh repo sync)")
        return

    out, err = await run_limited_command(repo_path, ["gh"] + fields)
    text = strip_control_codes(out)
    text = trim_output(text, 300, 6000)
    if err:
        text = f"gh error: {err}\n{text}"
    elif not text.strip():
        text = "gh command completed successfully (no output)."
    else:
        text = text.strip()
    await router.reply(sink, text)
    if not err:
        completion = _gh_clone_completion_hint(fields)
        if completion:
            await router.reply(sink, completion)


def _gh_clone_completion_hint(fields: list[str]) -> str:
    """Return a clone completion hint for gh clone-style commands."""
    repo_name = _infer_cloned_repo_name(fields)
    if repo_name:
        return f"Clone complete. Use `#codex-{repo_name}` for prompts."
    return ""


def _infer_cloned_repo_name(fields: list[str]) -> str:
    """Infer a repo name from gh clone arguments."""
    if len(fields) < 3:
        return ""
    if fields[0] == "repo" and fields[1] == "clone":
        if len(fields) >= 4 and not fields[3].startswith("-"):
            return _normalize_repo_hint(fields[3])
        return _normalize_repo_hint(fields[2])
    if fields[0] == "repo" and fields[1] == "create" and "--clone" in fields:
        for token in fields[2:]:
            if token.startswith("-"):
                continue
            return _normalize_repo_hint(token)
    return ""


def _normalize_repo_hint(token: str) -> str:
    candidate = token.strip().rstrip("/")
    if not candidate:
        return ""
    if candidate.endswith(".git"):
        candidate = candidate[: -len(".git")]
    if ":" in candidate and "/" in candidate:
        candidate = candidate.rsplit(":", 1)[1]
    if "/" in candidate:
        candidate = candidate.rsplit("/", 1)[1]
    if not candidate:
        return ""
    try:
        return pathutil.normalize_repo_name(candidate)
    except ValueError:
        return ""
