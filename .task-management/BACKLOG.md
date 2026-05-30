# BACKLOG

Rules:
- Use stable task IDs in format `TASK-####`.
- IDs are immutable and never reused.
- Bugs moved from `.task-management/BUGS.md` keep the same ID.
- When promoting a task to immediate TODO, move the task block to `.task-management/TODO.md` and keep the same ID.
- When completing a task, remove it from this file and append it to `.task-management/DONE.md`.
- When dropping a task, remove it from this file and append it to `.task-management/REMOVED.md`.

## Backlog tasks

- [TASK-0004] Role-based permissions model (Discord-role driven access tiers).

- [TASK-0020] Add Gemini CLI integration with operator-controlled delegation.
  - Goal: allow work to be delegated to Gemini CLI instead of Codex when requested.
  - Scope:
    - Add configurable Gemini CLI runner/invocation support alongside existing Codex runner path.
    - Add command/config controls to select delegation target per request/session (Codex vs Gemini) with explicit operator intent.
    - Preserve existing auth, sandbox, and transport safety expectations for delegated runs.
    - Ensure logs/audit entries identify which backend handled each run.
    - Document setup, required credentials, and usage examples for Gemini delegation.
  - Acceptance criteria:
    - Operator can run tasks through Gemini CLI without breaking existing Codex flows.
    - Backend selection is explicit and visible in command output/logging.
    - Targeted tests cover routing/runner selection and regression on default Codex behavior.

- [TASK-0006] Web-based/dashboard features (status/admin web surface, browser ops views).

- [TASK-0067] Choose and set a default `codex.model_reasoning_effort`.
  - Context: `config.yaml` leaves `model_reasoning_effort` unset, so Codex runs at its built-in default (medium) for `gpt-5.3-codex`. Reasoning effort is the largest token lever the bridge controls; per-session/`!c model` overrides already exist. `codebridge/codex.py:_reasoning_args` emits no override when empty.
  - Product decision: pick the default effort (e.g. `minimal`/`low`/`medium`) trading Codex token spend against answer quality for routine bridge work. Decide whether the default is global or per-repo/per-channel.
  - Scope once decided: set the default in `config.example.yaml`/`config.yaml`, document the override path in README/COMMAND_SURFACE, and (optionally) add per-repo default config.
  - Acceptance criteria: default applied when no session override is set; override still wins; docs updated; tests cover default-vs-override arg building.

- [TASK-0068] Decide budget pricing policy for cached input tokens.
  - Context: depends on [TASK-0066] tracking `cached_input_tokens`. Cache-read input tokens are billed far cheaper than fresh input by the API.
  - Product decision: should `!c budget` count cached tokens at full price (simple, conservative) or apply a discount weight to better reflect real cost? If discounted, what weight?
  - Scope once decided: apply the chosen weighting in `_budget_record_usage`/budget thresholds and reflect it in `!c budget status` output and docs.
  - Acceptance criteria: budget accounting matches the chosen policy; status output explains how cached tokens are counted; tests cover the weighting.

