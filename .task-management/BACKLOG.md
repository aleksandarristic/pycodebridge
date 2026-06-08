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
    - Implement as a `GeminiBackend` on the agent abstraction (TASK-0069) and reuse the per-session selection from TASK-0070 rather than building a parallel runner path.
    - Map Gemini CLI invocation/stream output into `AgentBackend.build_*` and `parse()` (`NormalizedEvent`).
    - Preserve existing auth, sandbox, and transport safety expectations for delegated runs.
    - Ensure logs/audit entries identify which backend handled each run.
    - Document setup, required credentials, and usage examples for Gemini delegation.
  - Acceptance criteria:
    - Operator can run tasks through Gemini CLI without breaking existing Codex flows.
    - Backend selection is explicit and visible in command output/logging.
    - Targeted tests cover routing/runner selection and regression on default Codex behavior.
  - Depends on: TASK-0069 (agent abstraction), TASK-0070 (per-session selection).

- [TASK-0069] Abstract the agent backend behind a common interface.
  - Goal: decouple Codex-specific CLI/JSONL logic from the runner plumbing and consumers so additional agent backends can be added without touching routing/session code. Pure refactor; no behavior change.
  - Scope:
    - New `codebridge/agents/` package:
      - `base.py`: move `Process`, `Options`, `run()`, `_merge_env` from `codex.py` verbatim (already backend-agnostic); add `NormalizedEvent` (fields: `session_id`, `texts`, `usage`, `error`, `raw`) and an `AgentBackend` protocol (`build_start`/`build_resume`/`build_resume_last`/`parse`).
      - `agents/codex.py`: `CodexBackend` implementing the protocol, wrapping existing `build_*` args plus `parse_event`/`agent_texts`/`display_texts`.
      - `agents/factory.py`: `build_backend(cfg, name) -> AgentBackend`, cached per name.
    - Normalize the parse seam in `router.py` `on_jsonl` (`router.py:2284`): `display_texts(evt)` -> `evt.texts` (lines 2326, 2341); `parse_event` fallback (line 2315) via the backend; `update_usage` reads `evt.usage` (line 2323). Drop direct `codex` imports at `router.py:23` and `routing/helpers.py:12`.
    - Keep `router.runner` as a `CodexBackend` for now (runtime selection added in TASK-0070).
  - Acceptance criteria:
    - No behavior change; existing tests pass (`tests/test_codex.py` and consumers) with import-only adjustments.
    - `codex.py` retains only Codex-specific arg/parse logic (or re-exports); shared subprocess plumbing lives in `agents/base.py`.
    - Routing/session code references `AgentBackend`/`NormalizedEvent`, not Codex-specific symbols.

- [TASK-0070] Per-session agent backend selection with `!agent` command.
  - Goal: let operators switch the agent backend per channel/session at runtime, resolved per run.
  - Scope:
    - Add `backend: str = ""` to `SessionState` (`sessions/state.py:18`) plus `from_dict` (line 168) and `to_dict` (line 220); empty falls back to `cfg.agent.default_backend`. Backward-compatible with existing state files.
    - Add `router.backend_for(channel_id, session) -> AgentBackend` (session backend -> factory, default fallback); replace the `router.runner.build_*` call sites (`handlers/core.py:69,109,124,126,129,267,269`; `commands/registry.py:745,749,751`) and the `run_codex` run call (`router.py:2026`).
    - New `!agent <name>` command mirroring the `!model` flow in `registry.py`; validate against known backends; persist `SessionState.backend`.
    - On backend switch: clear stored `thread_id` (cross-backend ids do not resume) and reset `model`/`effort` to the new backend's defaults, notifying the operator. Per-backend validation of `model`/`effort` (Codex effort set vs Claude `low|medium|high|xhigh|max`).
    - Config: add `agent.default_backend` (default `codex`); keep `cfg.codex.*`.
    - Audit/session-log: identify the backend per run (generalize `codex.exit`/`codex.error`/`codex.thread` event names or tag entries with backend).
  - Acceptance criteria:
    - Operator can switch backend per session; default Codex behavior is unchanged when `backend` is unset.
    - Switching clears the thread/session id and resets incompatible `model`/`effort` with a clear message.
    - Tests cover backend resolution, state round-trip with `backend`, the `!agent` command, and the switch-reset behavior.
  - Depends on: TASK-0069.

- [TASK-0071] Add Claude Code CLI backend.
  - Goal: implement `ClaudeBackend` on the agent abstraction so sessions can run via Claude Code's headless CLI.
  - Scope:
    - `agents/claude.py`: build `claude -p --output-format stream-json --verbose` invocations; map start/resume (`--resume <session-id>` / `--continue`), `--model`, `--effort`, working dir (`cwd` + `--add-dir`), and permission mode (`--permission-mode` / `--dangerously-skip-permissions`).
    - `parse()` against the real `stream-json` schema (capture a live sample first): `assistant`/content blocks -> `texts`; capture `session_id` from the init/system event; `result` usage -> `evt.usage`; errors -> `evt.error`.
    - Auth for Docker/headless: `claude setup-token` -> `CLAUDE_CODE_OAUTH_TOKEN`, or `ANTHROPIC_API_KEY`, or a mounted `CLAUDE_CONFIG_DIR`. Add `@anthropic-ai/claude-code` to the Dockerfile next to `@openai/codex` (line 23); extend the env allowlist (`codex.py:_merge_env`/`agents/base.py`) with Claude auth vars.
    - `claude:` config block (binary, permission_mode, model, effort, env).
    - Docs: DOCKER.md/README auth + usage examples.
  - Acceptance criteria:
    - A session with `backend=claude` runs end-to-end, streams output to Discord, and resumes by session id.
    - Tests cover the stream-json parser (fixture from a real sample) and Claude arg building.
  - Depends on: TASK-0069.
  - Blocked-on: a live `claude -p --output-format stream-json` sample to fix the event schema before implementing the parser.

- [TASK-0006] Web-based/dashboard features (status/admin web surface, browser ops views).

- [TASK-0066] Track cached input tokens and verify/fix per-event usage summation.
  - Context: `usage_from_event` (`routing/helpers.py:113`) reads only `input_tokens`/`output_tokens`/`total_tokens` and discards `cached_input_tokens`. `update_usage` (`router.py:3272`) **sums** usage from every JSONL event; if Codex reports cumulative running totals within a single `exec` run, session/budget totals are over-counted.
  - Goal: account for cached tokens and ensure run/session usage is counted correctly (incremental, not double-counted).
  - Scope:
    - Confirm the real `codex exec --json` usage event shape (incremental vs cumulative; field names for cached tokens) against live output, and record the finding in the ticket/commit. (Captured logs at `/Users/leka/Code/_bridge/logs` only contained `thread.started`/`turn.started`/`item.completed` with no usage event, so the shape still needs a live sample.)
    - Capture `cached_input_tokens` (and `cachedInputTokens`) in `UsageStats`; surface it in `!c stats` and the run-completion summary.
    - If usage is cumulative, fix `update_usage` to store the latest totals (or compute deltas) instead of summing.
  - Acceptance criteria:
    - Usage totals match Codex's reported totals for a multi-event run (no over-count).
    - Cached tokens are tracked and visible in stats/summary output.
    - Tests cover the corrected accounting and cached-token parsing; existing usage/budget tests pass.
  - Blocked-on: a real `codex exec --json` usage line (field names + cumulative-vs-incremental) before the summation fix can be implemented safely. Moved to backlog 2026-05-30 pending that sample.
