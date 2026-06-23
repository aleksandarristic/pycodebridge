"""Dispatch output formatting: per-agent status messages and aggregate summary."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, List

if TYPE_CHECKING:
    from ..platform.transport import ResponseSink

AGENT_EMOJI = {"codex": "⚙", "claude": "🧠", "gemini": "✨"}
_DEFAULT_EMOJI = "🤖"


@dataclass
class AgentResult:
    """Result of a single agent run."""
    agent: str
    success: bool
    files_changed: int = 0
    summary: str = ""
    error: str = ""


class DispatchOutputHandler:
    """Post per-agent and aggregate status messages to a sink."""

    def __init__(self, output_mode: str, sink: "ResponseSink") -> None:
        self._mode = (output_mode or "both").strip().lower()
        self._sink = sink

    def _emoji(self, agent: str) -> str:
        return AGENT_EMOJI.get(agent, _DEFAULT_EMOJI)

    def _per_agent(self) -> bool:
        return self._mode in {"per_agent", "both"}

    def _aggregate(self) -> bool:
        return self._mode in {"aggregate", "both"}

    async def on_agent_start(self, agent: str) -> None:
        if self._per_agent():
            await self._sink.send(f"{self._emoji(agent)} @{agent} running…")

    async def on_agent_done(self, result: AgentResult) -> None:
        if not self._per_agent():
            return
        emoji = self._emoji(result.agent)
        if result.success:
            changed = f" — {result.files_changed} file(s) changed" if result.files_changed else ""
            await self._sink.send(f"✅ {emoji} @{result.agent} done{changed}")
        else:
            err = f": {result.error}" if result.error else ""
            await self._sink.send(f"❌ {emoji} @{result.agent} failed{err}")

    async def on_all_done(self, results: List[AgentResult]) -> None:
        if not self._aggregate():
            return
        total = len(results)
        succeeded = sum(1 for r in results if r.success)
        lines = [f"**Dispatch complete** — {succeeded}/{total} agent(s) succeeded"]
        for r in results:
            emoji = self._emoji(r.agent)
            if r.success:
                detail = f"{r.files_changed} file(s) changed" if r.files_changed else "done"
                lines.append(f"• {emoji} @{r.agent} — {detail}")
            else:
                err = f" ({r.error})" if r.error else ""
                lines.append(f"• ❌ @{r.agent} — failed{err}")
        lines.append("")
        lines.append("Run `!c done` to open a PR, or `!c done --merge` to merge locally.")
        await self._sink.send("\n".join(lines))
