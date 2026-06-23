# TASK-0102 — Dispatch output: per-agent status messages and aggregate summary

**Branch:** `feature/dispatch-orchestrator`
**Status:** TODO

## Goal

Implement the output formatting layer for multi-agent dispatch runs. Controlled by
`cfg.dispatch.output_mode` (per_agent | aggregate | both). Each agent posts status
on start and finish; after all agents complete an aggregate summary is posted.

---

## Changes

### `codebridge/dispatch/output.py` (new file)

```python
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List

AGENT_EMOJI = {"codex": "⚙", "claude": "🧠", "gemini": "✨"}

@dataclass
class AgentResult:
    agent: str
    success: bool
    files_changed: int = 0
    summary: str = ""          # short description from agent output, may be empty
    error: str = ""            # set on failure

class DispatchOutputHandler:
    def __init__(self, output_mode: str, sink: MessageSink) -> None: ...

    async def on_agent_start(self, agent: str) -> None:
        """Post '⚙ @codex running…' if output_mode in {per_agent, both}."""

    async def on_agent_done(self, result: AgentResult) -> None:
        """Post '✅ @codex done — 3 files changed' or '❌ @codex failed' 
        if output_mode in {per_agent, both}."""

    async def on_all_done(self, results: List[AgentResult]) -> None:
        """Post aggregate summary if output_mode in {aggregate, both}.
        
        Format:
        **Dispatch complete** — 2/3 agents succeeded
        • ⚙ @codex — 4 files changed
        • 🧠 @claude — plan committed
        • ❌ @gemini — timed out
        
        Run `!c done` to open a PR, or `!c done --merge` to merge locally.
        """
```

### `codebridge/dispatch/orchestrator.py`

Replace the stub output call from TASK-0101 with `DispatchOutputHandler`:
```python
handler = DispatchOutputHandler(self._cfg.dispatch.output_mode, sink)
await handler.on_agent_start(agent)
# ... run agent ...
await handler.on_agent_done(result)
# after all agents:
await handler.on_all_done(results)
```

---

## Tests

**File:** `tests/test_dispatch_output.py`

Cover:
- `output_mode=per_agent` → `on_agent_start` and `on_agent_done` post; `on_all_done` does not post
- `output_mode=aggregate` → start/done silent; `on_all_done` posts
- `output_mode=both` → all three post
- Aggregate message lists all agents with correct success/fail emoji
- Failed agent shows error in aggregate
- `files_changed=0` still posts cleanly (no crash on zero)

---

## Done criteria

- Output messages match format above for all three modes
- Mode controlled entirely by `cfg.dispatch.output_mode`
- All tests pass; no existing tests broken
