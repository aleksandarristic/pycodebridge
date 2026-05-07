"""Repository helper command handlers."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from ..routing.helpers import TESTS_TIMEOUT, build_tree, run_limited_command, trim_output
from ..platform.transport import ResponseSink
from ..util.ansi import strip_control_codes

if TYPE_CHECKING:
    from ..routing.router import Router


async def handle_showrepo(router: "Router", sink: ResponseSink, repo_path: str) -> None:
    """Show a pruned repo tree for orientation."""
    text = build_tree(repo_path, max_depth=3)
    text = trim_output(text, 300, 6000)
    await router.reply(sink, text)


async def handle_showchanges(router: "Router", sink: ResponseSink, repo_path: str) -> None:
    """Show git status and diffstat for the repo."""
    status_task = run_limited_command(repo_path, ["git", "status", "--short", "--branch"])
    diff_task = run_limited_command(repo_path, ["git", "diff", "--stat"])
    (out, err), (out2, err2) = await asyncio.gather(status_task, diff_task)
    text = strip_control_codes(out + "\n" + out2)
    text = trim_output(text, 200, 4000)
    if err or err2:
        text = f"showchanges error: {err or err2}\n{text}"
    text = "```diff\n" + text + "\n```"
    await router.reply(sink, text)


async def handle_tests(router: "Router", sink: ResponseSink, repo_path: str) -> None:
    """Run tests for the repo (pytest -q)."""
    out, err = await run_limited_command(repo_path, ["pytest", "-q"], timeout=TESTS_TIMEOUT)
    text = strip_control_codes(out)
    text = trim_output(text, 200, 6000)
    if err:
        reason = "Tests failed"
        if isinstance(err, asyncio.TimeoutError):
            reason = "Tests timed out"
        text = f"{reason}: {err}\n{text}"
    await router.reply(sink, text)
