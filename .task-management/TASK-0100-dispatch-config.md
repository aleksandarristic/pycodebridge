# TASK-0100 — DispatchConfig: dataclass + YAML loading + validation

**Branch:** `feature/dispatch-orchestrator`
**Status:** TODO

## Goal

Add a `DispatchConfig` dataclass to `codebridge/config.py` and wire it fully into the
config loading pipeline. Covers output mode, close mode, and the orchestrator planning
prompt template.

---

## Changes

### `codebridge/config.py`

**New constants:**
```python
DEFAULT_DISPATCH_OUTPUT_MODE = "both"      # per_agent | aggregate | both
DEFAULT_DISPATCH_CLOSE_MODE = "pr"         # pr | merge
DEFAULT_DISPATCH_PLAN_PROMPT = (
    "You are the orchestrator for a multi-agent coding session.\n"
    "Analyse the user request below and produce a concise implementation plan.\n"
    "The plan will be passed as context to the other agents.\n\n"
    "User request: {{USER_REQUEST}}\n\n"
    "Agents available: {{AGENTS}}\n"
)
```

**New dataclass (add after `WorktreeConfig`):**
```python
@dataclass
class DispatchConfig:
    """Multi-agent dispatch configuration."""
    output_mode: str = DEFAULT_DISPATCH_OUTPUT_MODE   # per_agent | aggregate | both
    close_mode: str = DEFAULT_DISPATCH_CLOSE_MODE     # pr | merge
    plan_prompt: str = DEFAULT_DISPATCH_PLAN_PROMPT   # template for orchestrator planning step
```

**`Config` dataclass** — add field:
```python
dispatch: DispatchConfig = field(default_factory=DispatchConfig)
```

**`_apply_dict`** — read `dispatch:` YAML section:
```python
dispatch = raw.get("dispatch", {}) or {}
cfg.dispatch.output_mode = str(dispatch.get("output_mode", cfg.dispatch.output_mode) or DEFAULT_DISPATCH_OUTPUT_MODE)
cfg.dispatch.close_mode = str(dispatch.get("close_mode", cfg.dispatch.close_mode) or DEFAULT_DISPATCH_CLOSE_MODE)
cfg.dispatch.plan_prompt = str(dispatch.get("plan_prompt", cfg.dispatch.plan_prompt) or DEFAULT_DISPATCH_PLAN_PROMPT)
```

**`_validate`** — add:
```python
if cfg.dispatch.output_mode not in {"per_agent", "aggregate", "both"}:
    raise ValueError("dispatch.output_mode must be per_agent|aggregate|both")
if cfg.dispatch.close_mode not in {"pr", "merge"}:
    raise ValueError("dispatch.close_mode must be pr|merge")
```

### `config.example.yaml`

Add section after `worktrees:`:
```yaml
dispatch:
  # Controls what the bot posts during and after a multi-agent run.
  #   per_agent  — status message per agent (start + finish)
  #   aggregate  — single summary after all agents finish
  #   both       — per-agent messages AND an aggregate summary (default)
  output_mode: both

  # What happens when the user runs `!c done`.
  #   pr     — push task branch and open a draft PR (default, user reviews on GitHub)
  #   merge  — merge task branch into main locally and push
  close_mode: pr

  # Prompt template used when @claude orchestrates a fan-out.
  # {{USER_REQUEST}} and {{AGENTS}} are substituted at runtime.
  # plan_prompt: |
  #   You are the orchestrator...
```

### `config.docker.example.yaml`

Add same `dispatch:` section (identical content).

---

## Tests

**File:** `tests/test_config_dispatch.py`

Cover:
- Defaults load when `dispatch:` key absent
- `output_mode` validation rejects unknown values
- `close_mode` validation rejects unknown values
- Valid YAML round-trips all three fields
- `plan_prompt` override from YAML preserved (not reset to default)

---

## Done criteria

- `cfg.dispatch` populated from YAML or defaults in all configs
- Validation tests pass
- No existing tests broken
