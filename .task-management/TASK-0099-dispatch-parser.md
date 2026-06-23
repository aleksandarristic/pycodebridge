# TASK-0099 — Dispatch parser: @agent extraction and fan-out detection

**Branch:** `feature/dispatch-orchestrator`
**Status:** TODO

## Goal

Parse `@agent` mentions out of a `!c` message to determine which backend(s) to dispatch
to, and whether the invocation is solo, sequential, or a parallel fan-out.

This is pure parsing logic with no I/O — a standalone module that the router and
orchestrator flow (TASK-0101) will call.

---

## Changes

### `codebridge/dispatch/parser.py` (new file)

```python
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List

KNOWN_AGENTS = {"codex", "claude", "gemini"}

@dataclass
class DispatchSpec:
    agents: List[str]          # ordered list of @agent names extracted, e.g. ["claude", "codex"]
    prompt: str                # message with @mentions stripped
    is_orchestrated: bool      # True when claude leads + other agents follow
    is_fanout: bool            # True when >1 agent runs in parallel
    raw: str                   # original message unchanged

def parse_dispatch(message: str) -> DispatchSpec | None:
    """
    Return a DispatchSpec if the message contains @agent mentions, else None.

    Rules:
    - @claude + other agents → is_orchestrated=True, is_fanout=True (claude plans first)
    - multiple non-claude agents → is_fanout=True
    - single agent → solo dispatch
    - no @mentions → return None (caller uses default_backend)
    """
```

Edge cases to handle:
- `@Claude` / `@CODEX` — normalise to lowercase
- Unknown `@word` that isn't a known agent — leave in prompt, do not treat as agent
- Duplicate mentions (`@codex @codex`) — deduplicate, preserve first order
- Message that is only `@mentions` with no other text — `prompt` becomes `""` (valid, caller decides)

### `codebridge/dispatch/__init__.py` (new file)

Empty or re-export `parse_dispatch` and `DispatchSpec`.

---

## Tests

**File:** `tests/test_dispatch_parser.py`

Cover:
- Single `@codex` → `agents=["codex"]`, `is_fanout=False`, `is_orchestrated=False`
- `@claude` alone → solo, not orchestrated (orchestrated only when other agents follow)
- `@claude @codex implement auth` → `agents=["claude","codex"]`, `is_orchestrated=True`, `is_fanout=True`, prompt=`"implement auth"`
- `@codex @gemini build UI` → `is_fanout=True`, `is_orchestrated=False`
- `@claude plan this, dispatch @codex and @gemini` → orchestrated fan-out, 3 agents
- No mentions → returns `None`
- Mixed case `@Codex` → normalised
- Unknown `@foo` → not treated as agent, left in prompt
- Duplicate `@codex @codex` → deduplicated

---

## Done criteria

- `parse_dispatch()` returns correct `DispatchSpec` for all cases above
- Returns `None` for messages with no known agent mentions
- All tests pass
- No changes to existing router or backend code in this task
