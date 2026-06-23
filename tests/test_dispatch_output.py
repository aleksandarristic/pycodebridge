"""Tests for DispatchOutputHandler."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import List

from codebridge.dispatch.output import AgentResult, DispatchOutputHandler


def run(coro):
    return asyncio.run(coro)


@dataclass
class FakeSink:
    messages: List[str] = field(default_factory=list)
    channel_id: str = "chan1"

    async def send(self, content, thread_id=None, reply_to_id=None):
        self.messages.append(content)


# ---------------------------------------------------------------------------
# per_agent mode
# ---------------------------------------------------------------------------

def test_per_agent_start_posts_message():
    sink = FakeSink()
    h = DispatchOutputHandler("per_agent", sink)
    run(h.on_agent_start("codex"))
    assert len(sink.messages) == 1
    assert "@codex" in sink.messages[0]
    assert "running" in sink.messages[0]


def test_per_agent_done_success_posts_message():
    sink = FakeSink()
    h = DispatchOutputHandler("per_agent", sink)
    run(h.on_agent_done(AgentResult(agent="codex", success=True, files_changed=3)))
    assert len(sink.messages) == 1
    assert "✅" in sink.messages[0]
    assert "@codex" in sink.messages[0]
    assert "3" in sink.messages[0]


def test_per_agent_done_failure_posts_message():
    sink = FakeSink()
    h = DispatchOutputHandler("per_agent", sink)
    run(h.on_agent_done(AgentResult(agent="gemini", success=False, error="timed out")))
    assert "❌" in sink.messages[0]
    assert "timed out" in sink.messages[0]


def test_per_agent_all_done_silent():
    sink = FakeSink()
    h = DispatchOutputHandler("per_agent", sink)
    run(h.on_all_done([AgentResult(agent="codex", success=True)]))
    assert len(sink.messages) == 0


# ---------------------------------------------------------------------------
# aggregate mode
# ---------------------------------------------------------------------------

def test_aggregate_start_silent():
    sink = FakeSink()
    h = DispatchOutputHandler("aggregate", sink)
    run(h.on_agent_start("codex"))
    assert len(sink.messages) == 0


def test_aggregate_done_silent():
    sink = FakeSink()
    h = DispatchOutputHandler("aggregate", sink)
    run(h.on_agent_done(AgentResult(agent="codex", success=True)))
    assert len(sink.messages) == 0


def test_aggregate_all_done_posts_summary():
    sink = FakeSink()
    h = DispatchOutputHandler("aggregate", sink)
    results = [
        AgentResult(agent="claude", success=True, files_changed=1),
        AgentResult(agent="codex", success=True, files_changed=4),
        AgentResult(agent="gemini", success=False, error="not found"),
    ]
    run(h.on_all_done(results))
    assert len(sink.messages) == 1
    msg = sink.messages[0]
    assert "2/3" in msg
    assert "@claude" in msg
    assert "@codex" in msg
    assert "@gemini" in msg
    assert "not found" in msg
    assert "!c done" in msg


# ---------------------------------------------------------------------------
# both mode (default)
# ---------------------------------------------------------------------------

def test_both_mode_posts_everything():
    sink = FakeSink()
    h = DispatchOutputHandler("both", sink)
    run(h.on_agent_start("codex"))
    run(h.on_agent_done(AgentResult(agent="codex", success=True, files_changed=2)))
    run(h.on_all_done([AgentResult(agent="codex", success=True, files_changed=2)]))
    assert len(sink.messages) == 3  # start + done + aggregate


def test_aggregate_output_silent():
    sink = FakeSink()
    h = DispatchOutputHandler("aggregate", sink)
    run(h.on_agent_output("codex", "some live text", 2000))
    assert len(sink.messages) == 0


def test_per_agent_output_relays():
    sink = FakeSink()
    h = DispatchOutputHandler("per_agent", sink)
    run(h.on_agent_output("codex", "hello world", 2000))
    assert len(sink.messages) == 1
    assert "@codex" in sink.messages[0]
    assert "hello world" in sink.messages[0]


def test_both_mode_output_relays():
    sink = FakeSink()
    h = DispatchOutputHandler("both", sink)
    run(h.on_agent_output("claude", "thinking…", 2000))
    assert len(sink.messages) == 1


def test_zero_files_changed_does_not_crash():
    sink = FakeSink()
    h = DispatchOutputHandler("both", sink)
    run(h.on_agent_done(AgentResult(agent="codex", success=True, files_changed=0)))
    assert len(sink.messages) == 1
