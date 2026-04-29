# TODO (Immediate)

Rules:
- Use stable task IDs in format `TASK-####`.
- IDs are immutable and never reused.
- Tasks promoted from `.task-management/BUGS.md` keep the same ID.
- When moving a task to backlog, keep the same ID.
- When completing a task, remove it from this file and append it to `.task-management/DONE.md`.
- When dropping a task, remove it from this file and append it to `.task-management/REMOVED.md`.

## Active tasks

Ordered by estimated ROI (highest first), balancing user impact, implementation scope, and delivery risk.

- [TASK-0029] Parallelize independent helper subprocesses on read-only command paths.
  - Goal: reduce operator-perceived latency for commands that currently await multiple independent subprocesses in sequence.
  - Scope:
    - Review read-only helpers such as `showchanges`, `updates`, and similar status/diagnostic flows.
    - Run independent subprocesses concurrently where outputs do not depend on one another.
    - Preserve existing timeout/error semantics and user-visible output ordering.
  - Acceptance criteria:
    - Commands that combine multiple independent helper calls no longer block on fully serialized subprocess execution.
    - Targeted tests cover successful parallel aggregation and failure/timeout handling.

- [TASK-0027] Cache-first model listing to avoid unnecessary Codex `/model` runs.
  - Goal: eliminate avoidable token spend when listing available models.
  - Scope:
    - Change `!c models` to use the local models cache first when it is present and valid.
    - Only invoke Codex for model discovery on explicit refresh or cache miss/staleness.
    - Keep current parsing/normalization behavior for refreshed results.
    - Document how operators can refresh the cache when needed.
  - Acceptance criteria:
    - `!c models` does not start a Codex session when cached model data is sufficient.
    - Operators still have a supported way to refresh the list explicitly.
    - Targeted tests cover cache-hit, cache-miss, and refresh behavior.

- [TASK-0031] Reduce reply-path overhead from repeated chunking and nested send loops.
  - Goal: tighten the output pipeline so Discord replies are formatted and chunked once per message path where practical.
  - Scope:
    - Review router/helper code paths that pre-chunk output and then call reply helpers that chunk again.
    - Simplify helper APIs so call sites can pass full text and let one layer own chunking.
    - Preserve thread/reply context behavior and message size safety.
  - Acceptance criteria:
    - Common helper and streaming output paths avoid redundant chunking/splitting work.
    - Reply behavior remains correct for long outputs and contextual sinks.
    - Targeted tests cover long-message chunking behavior after the refactor.

- [TASK-0025] Session compaction and idle-expiry defaults for token control.
  - Goal: reduce token spend from endlessly resumed long-lived Codex threads.
  - Scope:
    - Revisit the default `state.session_idle_ttl_seconds` so sessions do not implicitly live forever.
    - Add a compaction flow that captures a short structured session summary before starting a fresh thread.
    - Reuse the compacted summary when restarting instead of dragging full historical thread context forward.
    - Expose the operator-facing behavior clearly in command replies/docs (`continue`, `new`, compacted restart).
  - Acceptance criteria:
    - Idle sessions can be configured to expire by default instead of resuming indefinitely.
    - Operators have a supported path to restart from a compact summary rather than full prior context.
    - Targeted tests cover idle-expiry prompting and compacted restart behavior.

- [TASK-0030] Add in-memory state caching for hot read paths.
  - Goal: avoid repeated lock + JSON disk reads on message-handling and status-heavy paths.
  - Scope:
    - Introduce a coherent in-memory snapshot/cache for `state.load()` reads, invalidated on `state.update()`/`save()`.
    - Audit hot router/session paths that repeatedly reload state during a single request.
    - Preserve file-lock safety and correctness for cross-process use.
  - Acceptance criteria:
    - Common read-heavy command/message paths avoid redundant disk loads without serving stale data after local writes.
    - State semantics remain correct under locking and process restarts.
    - Targeted tests cover cache invalidation and compatibility with existing state mutations.

- [TASK-0026] Budget-aware token guardrails for oversized runs and sessions.
  - Goal: turn token usage reporting into active spend control.
  - Scope:
    - Add per-run and per-session thresholds in addition to the current aggregate channel/user budgets.
    - Emit early warnings when a run is becoming unusually expensive.
    - Optionally recommend or trigger safer follow-up actions such as starting a fresh session.
    - Record enough metadata to distinguish cumulative session bloat from a single large run.
  - Acceptance criteria:
    - Operators can configure thresholds that catch expensive runs before they become recurring waste.
    - User-visible notices distinguish channel/user budgets from run/session-specific token growth.
    - Targeted tests cover warning/block behavior and usage accounting.

- [TASK-0002] Final-message ordering hardening for run lifecycle output.
  - Goal: prevent stale/intermediate progress updates from appearing after a run-complete message.
  - Scope:
    - Emit a single authoritative terminal event for each run (success/failure/cancelled).
    - Suppress or ignore late progress events once terminal state is set.
    - Add clear run-state metadata so transports can order/filter consistently.
  - Acceptance criteria:
    - After terminal event emission, no additional progress update is delivered for that run.
    - User-visible last message is always terminal status for the run.
    - Regression test covers out-of-order event delivery scenario.

- [TASK-0028] Lean default prompt profiles for lower recurring token overhead.
  - Goal: reduce repeated prompt boilerplate on new sessions and spec flows.
  - Scope:
    - Shorten the default start/session bootstrap prompt while preserving required operational guidance.
    - Review the default spec prompt and move durable instructions into repo files/docs where practical.
    - Add a lightweight notion of prompt profiles or recommended defaults for common task classes.
    - Document recommended model/reasoning defaults for routine vs complex work.
  - Acceptance criteria:
    - Default prompts are materially shorter without regressing expected bridge behavior.
    - Spec/setup instructions avoid repeating large static guidance in every fresh session.
    - Docs include a brief recommendation for model and reasoning settings by task complexity.

- [TASK-0032] Async/batched session JSONL logging for high-output runs.
  - Goal: lower per-event filesystem overhead during active Codex streams.
  - Scope:
    - Review synchronous `session_jsonl` append behavior on hot streaming paths.
    - Batch or buffer append operations behind a safe async writer or flush policy.
    - Keep crash-safety and log usability tradeoffs explicit and configurable.
  - Acceptance criteria:
    - High-output runs spend less time blocking on per-line log file writes.
    - Logging remains ordered and durable within the documented guarantees.
    - Targeted tests cover flush/ordering behavior and failure handling.

- [TASK-0005] Knowledge shortcuts/macros for repeatable repo workflows.

- [TASK-0004] Role-based permissions model (Discord-role driven access tiers).

- [TASK-0003] Compose + global skill defaults for cross-repo persistence (deferred).
  - Goal: define and document a non-`AGENTS.md` channel for durable operator defaults across repos/sessions.
  - Approach:
    - Use user-level Codex skills persisted in mounted Codex home (`CODEX_AUTH_HOST -> /workspace/home/.codex` in Compose).
    - Optionally set `codex.env.CODEX_HOME=/workspace/home/.codex` in `config.docker.yaml` for explicit subprocess behavior.
  - Deliverables:
    - Add docs snippet with host-side skill path, minimal `SKILL.md` example, and Compose restart/apply steps.
    - Clarify precedence/coexistence with per-repo `AGENTS.md`.

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
