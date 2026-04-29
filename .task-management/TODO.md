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

- [TASK-0034] Command model redesign around a minimal core workflow.
  - Goal: define a simpler command architecture that stays usable even though the bridge already exposes `git`, `gh`, and Codex capabilities.
  - Analysis summary:
    - Realistically needed commands appear to cluster into a small core:
      - orientation/help: `help`, `status`
      - session lifecycle: `start`, `resume`, `use`, `reset`
      - active-run control: `answer`, `approve`, `deny`, `steer`, `stop`/`interrupt`, `wait`
      - repo inspection: `show`, `changes`, `tests`, `branch`
      - raw tool escape hatches: `git`, `gh`
      - admin/setup only: repo lifecycle, config/options, logs/audit, security unlock/lock
    - Several commands likely need consolidation or demotion from the primary surface:
      - `stats`, `budget`, and `peek` overlap as diagnostic/status views.
      - `reset`, `purge`, and `session ...` spread session lifecycle across too many verbs.
      - `logs` and `audit` are power-user/admin features and probably should not compete with core workflow commands.
      - `thread` is highly specialized and should likely be hidden from normal operator flow.
  - Scope:
    - Propose a minimal core command set for normal channel usage.
    - Define which commands remain first-class, which move under subcommands/admin namespaces, and which become deprecated aliases only.
    - Recommend a consistent structure for channel commands versus DM/admin commands.
  - Acceptance criteria:
    - The redesign clearly separates core workflow commands from power/admin commands.
    - Overlapping commands are either merged, nested, or explicitly marked for deprecation.
    - The proposal includes migration guidance for existing operators and scripts.

- [TASK-0035] Command information architecture, naming, and help-system rewrite.
  - Goal: reorganize command naming and help output so the bridge is easier to learn and operate.
  - Analysis summary:
    - The bridge currently mixes flat verbs, aliases, and shorthands in a way that increases cognitive load.
    - The help experience should emphasize a short “golden path” and treat advanced/admin commands as secondary.
    - A better structure is likely:
      - keep `!c` as the canonical namespace
      - keep only a very small number of top-level shorthands for active-run interaction (`!a`, `!s`, maybe `!y`/`!n`)
      - group advanced features under clearer families such as `session`, `admin`, `diag`, or similar
      - preserve `git` and `gh` as explicit escape hatches instead of duplicating too many specialized wrappers
  - Scope:
    - Redesign command naming, grouping, and help rendering around progressive disclosure.
    - Define which shortcuts remain because they materially improve chat ergonomics and which aliases should be removed from prominent docs.
    - Update user-facing docs/help so the preferred workflow is obvious in both channel and DM contexts.
  - Acceptance criteria:
    - The help/index output presents a short primary workflow before advanced/admin commands.
    - Shortcut and alias policy is explicit and intentionally limited.
    - Docs reflect the new command organization and deprecation plan.

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
