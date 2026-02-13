"""GitHub CLI helper command handlers."""

from __future__ import annotations

import shlex
from typing import TYPE_CHECKING

from ..router_helpers import run_limited_command, trim_output
from ..transport import ResponseSink
from ..util.ansi import strip_control_codes
from ..util.chunk import chunk_text

if TYPE_CHECKING:
    from ..router import Router


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
    text = text.strip() or "(no output)"
    for chunk in chunk_text(text, router.cfg.discord.max_discord_message_chars):
        await router.reply(sink, chunk)
