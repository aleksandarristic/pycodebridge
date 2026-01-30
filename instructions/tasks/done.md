# Done Tasks

## TOC
- 1) DONE - Project bootstrap
- 2) DONE - Config loader (YAML only)
- 3) DONE - Path containment utility
- 4) DONE - State management
- 5) DONE - Audit logging
- 6) DONE - Codex runner
- 7) DONE - Message formatting utilities
- 8) DONE - Per-channel queue and job controls
- 9) DONE - Discord bot wiring
- 10) DONE - Command routing
- 11) DONE - Repo bootstrap commands
- 12) DONE - Logging
- 13) DONE - Tests
- 14) DONE - Docs
- 15) DONE - Packaging/runtime ergonomics
- 16) DONE - Windows/macOS compatibility pass
- 17) DONE - Requirements files
- 18) DONE - Skills documentation
- 19) DONE - Graceful shutdown on Ctrl-C
- 20) DONE - Reliable typing indicator
- 21) DONE - PEP8 docstrings
- 22) DONE - Router refactor (1-2 day wins)
- 23) DONE - SessionService layer
- 24) DONE - Command registry
- 25) DONE - Transport abstraction (phase 1)
- 26) DONE - Transport abstraction (phase 2)
- 27) DONE - Architecture diagram (Mermaid)
- 28) DONE - Slack adapter skeleton
- 29) DONE - Transport test expansion
- 30) DONE - Documentation cleanup for multi-transport + local paths
- 32) DONE - Slack/Telegram setup docs
- 33) DONE - Telegram adapter scaffold
- 47) DONE - Add transport capabilities and guard router behaviors (issue plan)
- 48) DONE - Extract upload/download handling from Router (issue plan)
- 49) DONE - Expand threading tests for Discord/Telegram (issue plan)
- 50) DONE - Capability conformance tests (issue plan)
- 51) DONE - Router tests for DM uploads/download gating (issue plan)
- 52) DONE - Document transport capabilities (issue plan)
- 53) DONE - SessionCoordinator consolidation (issue plan)
- 54) DONE - Adapter contract fixtures (issue plan)
- 55) DONE - Adapter integration harness (issue plan)
- 56) DONE - Router surface cleanup (issue plan)
- 57) DONE - Standardize command routing utilities (issue plan)
- 58) DONE - Consolidate audit helper calls (issue plan)
- 59) DONE - Model selection and reporting (issue plan)
- 60) DONE - Clarify adapter contract usage (issue plan)
- 62) DONE - Finish Router surface cleanup (issue plan)
- 65) DONE - Add shutdown summary message (issue plan)
- 66) DONE - Enrich startup DM (issue plan)
- 67) DONE - Add immediate Codex `/status` retrieval path (issue plan)
- 68) DONE - Parse and format Codex `/status` output (issue plan)
- 69) DONE - Integrate parsed `/status` into `!c status` (issue plan)
- 37) DONE - Telegram adapter completion
- 38) DONE - README integrations section
- 39) DONE - Audit log redaction toggle
- 40) DONE - DM command collision resolution
- 41) DONE - DM repo binding commands (prefix-only)
- 42) DONE - Repo file upload/download support
- 44) DONE - Telegram file upload/download support
- 45) DONE - Platform thread context standardization
- 43) DONE - Improve operational logging

---

1) DONE - Project bootstrap
- Initialize Python package layout under `codebridge/` and `cmd/`.
- Add `pyproject.toml` with Python 3.14 (fallback 3.13/3.12) and deps:
  - discord.py
  - PyYAML
  - python-dotenv
  - filelock
  - pytest
- Add `.gitignore` with `.venv`, `__pycache__`, logs, state files.

2) DONE - Config loader (YAML only)
- Load YAML config with defaults.
- Support env/`~`/`%APPDATA%` expansion for paths.
- Add `.env` loading via python-dotenv (default to repo root).
- Validate required fields and compile channel regex.

3) DONE - Path containment utility
- Implement secure repo resolution and `.git` existence check.
- Ensure traversal/symlink escape protection.

4) DONE - State management
- Implement `state.json` read/write with filelock.
- Support migration of legacy single-session fields if present.
- Store sticky session selections per user.

5) DONE - Audit logging
- Per-channel/session/thread directory layout.
- Monotonic sequence numbers per thread.
- Write request.json, codex.jsonl, discord_out.txt, codex.stderr.txt.
- Read summaries for `!c logs`.

6) DONE - Codex runner
- Async subprocess runner for `codex exec --json ...`.
- Parse JSONL, extract agent messages and thread_id.
- Provide stop (ESC), interrupt (SIGINT), kill controls.
- Allow per-session model overrides.
- Connect stderr stream to audit logger and capture exit status for router.

7) DONE - Message formatting utilities
- ANSI/control stripping.
- Chunking to Discord size.
- User-input prompt detection and `Codex asks:` prefix.
- Diff fence rendering where appropriate.

8) DONE - Per-channel queue and job controls
- Serialized processing per channel+session.
- `ps`, `cancel`, `rerun` with job IDs.
- Track active job + queued positions.

9) DONE - Discord bot wiring
- discord.py client with required intents.
- Message handler for channels and DMs.
- Typing indicator keepalive while running.
- Typing indicator keepalive task and status message management.

10) DONE - Command routing
- Implement all commands from spec (start/resume/choose/stop/kill/quit/etc.).
- Git helpers with safe flag allowlist and timeouts.
- Repo helpers: showrepo/showchanges/tests.
- DM admin commands gated by config.
- “I’m sorry, Dave...” wrapper for forbidden/invalid commands.
- Session limit (max 3) and sticky session selection.

11) DONE - Repo bootstrap commands
- `createrepo`, `clonerepo`, `copyrepo` with containment rules.
- Optional AGENTS.md template seeding.
- `spec` flow to generate instructions/spec.md + tasks.

12) DONE - Logging
- stdlib logging, human-readable format.
- Log to stdout and rotating file in log_dir.

13) DONE - Tests
- Pytest suite mirroring Go tests: config/path/state/audit/router/queue/codex.
- Add small integration tests with fake codex output.

14) DONE - Docs
- README with setup, config reference, commands, DM admin notes.
- DISCORD.md with bot intents and invite setup.

15) DONE - Packaging/runtime ergonomics
- Add `__main__.py` or console script entrypoint.
- Add `pip install -e .` and `python -m cmd.bridge` run notes.

16) DONE - Windows/macOS compatibility pass
- Verify path expansion, file locks, and signal handling.
- Replace SIGINT-only logic with cross-platform handling where needed.

17) DONE - Requirements files
- Add `requirements.txt` and `requirements-dev.txt` with pinned versions.
- Keep dev requirements installing into `.venv`.

18) DONE - Skills documentation
- Add `.codex/skills/README.md` with when-to-use guidance and overlap notes.
- Reference skill usage in `AGENTS.md` and `instructions/instructions.md`.

19) DONE - Graceful shutdown on Ctrl-C
- Catch KeyboardInterrupt/CancelledError and close the Discord client cleanly to avoid traceback spam.
- Optional: add SIGINT/SIGTERM handlers (non-Windows) to call `client.close()` and log a single shutdown line.
- Validate by starting the app, pressing Ctrl-C, and confirming no traceback.

20) DONE - Reliable typing indicator
- Replace `channel.trigger_typing()` loop with `async with channel.typing():` (or manage a long-lived typing context) so typing stays visible.
- Keep fallback timer if needed, but prefer the official typing context.
- Validate by sending a long-running command and confirming the typing indicator stays on.

21) DONE - PEP8 docstrings
- Add PEP8-style docstrings to Python modules/classes/functions where missing.
- Keep docstrings concise and behavior-focused; avoid altering logic.
- Run tests to confirm no regressions.

22) DONE - Router refactor (1-2 day wins)
- Split `codebridge/router.py` into handler modules (core, DM admin, repo helpers, git helpers).
- Extract shared helper functions into a `router_helpers.py`.
- Add unit tests for handler entry points where feasible.

23) DONE - SessionService layer
- Introduce a `SessionService` to encapsulate session state updates, pending conflict handling, and active process tracking.
- Replace direct map access in `Router` with the service to reduce locking complexity.
- Add unit tests covering SessionService behavior (conflict TTL, active tracking).

24) DONE - Command registry
- Implement a table-driven command registry to dispatch handlers.
- Generate help text from the registry to avoid drift.
- Add unit tests for registry parsing and help output.

25) DONE - Transport abstraction (phase 1)
- Define a platform-agnostic `MessageEvent` and `ResponseSink` contract.
- Update Router to consume these interfaces rather than discord.py types.
- Add unit tests for event parsing and sink behavior.

26) DONE - Transport abstraction (phase 2)
- Implement a Discord adapter that maps discord.py events to `MessageEvent` and provides a `ResponseSink`.
- Keep existing behavior and typing indicators intact under the adapter.
- Add a config option/flag for selecting adapters (Discord only for now).

27) DONE - Architecture diagram (Mermaid)
- Create a Mermaid diagram describing core modules, adapters, and data flow.
- Store it in `docs/architecture.mmd` (or similar) and reference from README.

28) DONE - Slack adapter skeleton
- Create a Slack transport adapter stub (event mapping + response sink interface implementation).
- Keep it behind `transport.adapter` selection without changing default behavior.
- Add docs note that Slack is scaffold-only until API integration is completed.

29) DONE - Transport test expansion
- Add adapter mapping tests for Discord adapter (MessageEvent fields, sink behaviors).
- Add ResponseSink pin/typing behavior tests via fakes/mocks where possible.
- Ensure tests stay unit-level with no external API calls.

30) DONE - Documentation cleanup for multi-transport + local paths
- Review docs to remove Discord-specific framing where transport-agnostic wording fits.
- Remove local filesystem references from docs including `AGENTS.md`, `instructions/instructions.md`, and `instructions/tasks.md`.
- Keep Discord mentioned only where it is a concrete adapter/example.

32) DONE - Slack/Telegram setup docs
- Add `SLACK.md` with bot/app setup, tokens, permissions, and webhook/polling notes.
- Add `TELEGRAM.md` with bot setup, token placement, webhook/polling notes, and a broader explanation of chat types (1:1, group, supergroup) vs room/DM semantics.
- Reference the new docs from README.

33) DONE - Telegram adapter scaffold
- Add a Telegram adapter scaffold (event mapping + response sink interface implementation).
- Keep it behind `transport.adapter` selection without changing default behavior.
- Add docs note that Telegram is scaffold-only until API integration is completed.

47) DONE - Add transport capabilities and guard router behaviors (issue plan)
- Owner: TBD
- Subtasks:
  - Define a capabilities descriptor (threads/uploads/typing/downloads) in `transport.py`.
  - Implement per-adapter capability reporting.
  - Gate Router actions based on capabilities (upload/download/typing/threading).
  - Add unit tests for capability gating.

48) DONE - Extract upload/download handling from Router (issue plan)
- Owner: TBD
- Subtasks:
  - Create upload/download service module (path validation, save logic, replies).
  - Refactor Router to delegate to the service; keep orchestration in Router.
  - Add tests for upload/download flows with mocked attachments/sinks.

49) DONE - Expand threading tests for Discord/Telegram (issue plan)
- Owner: TBD
- Subtasks:
  - Add adapter tests for Discord thread id mapping and Telegram reply/topic mapping.
  - Add Router test verifying thread context propagation via sink wrapper.

50) DONE - Capability conformance tests (issue plan)
- Owner: TBD
- Subtasks:
  - Add unit tests asserting `ResponseSink.capabilities()` for each adapter.
  - Add negative tests ensuring unsupported operations are gated by Router.

51) DONE - Router tests for DM uploads/download gating (issue plan)
- Owner: TBD
- Subtasks:
  - Add tests for DM-bound uploads and download permission errors when capabilities are false.
  - Add tests for allowed upload/download flows when capabilities are true.

52) DONE - Document transport capabilities (issue plan)
- Owner: TBD
- Subtasks:
  - Document capabilities (threads/replies/uploads/downloads/typing) in `README.md`.
  - Add adapter-specific notes in `DISCORD.md` and `TELEGRAM.md`.

53) DONE - SessionCoordinator consolidation (issue plan)
- Owner: TBD
- Subtasks:
  - Design a coordinator API that owns queue + active process lifecycle.
  - Refactor Router/SessionService/Queue to use coordinator transitions.
  - Add a state-transition test matrix for start/resume/stop/kill/pending.

54) DONE - Adapter contract fixtures (issue plan)
- Owner: TBD
- Subtasks:
  - Define typed fixtures for each adapter input event.
  - Add golden payload tests for Slack/Telegram/Discord mappings.
  - Add tests for thread/reply extraction across adapters.

55) DONE - Adapter integration harness (issue plan)
- Owner: TBD
- Subtasks:
  - Build an in-memory adapter harness to simulate end-to-end flows.
  - Add scenarios for start/resume/stop/kill, file transfers, and threading.
  - Run harness in CI (unit-level, no external API calls).

56) DONE - Router surface cleanup (issue plan)
- Owner: TBD
- Complexity: Medium
- Subtasks:
  - Identify Router methods that can move into `handlers/*` or small service helpers.
  - Extract at least one low-risk block (status formatting or reply helpers) into a dedicated module.
  - Add/update unit tests covering the moved behavior.

57) DONE - Standardize command routing utilities (issue plan)
- Owner: TBD
- Complexity: Medium
- Subtasks:
  - Audit duplicated parsing/validation logic across handlers.
  - Add shared helpers in `command_parse.py` or `command_registry.py`.
  - Update handlers to use shared utilities and add regression tests.

60) DONE - Clarify adapter contract usage (issue plan)
- Owner: TBD
- Complexity: Medium
- Subtasks:
  - Identify adapter-specific conditionals in Router and handlers.
  - Prefer capabilities checks or adapter-layer behavior where possible.
  - Add tests covering any adjusted routing behavior.

62) DONE - Finish Router surface cleanup (issue plan)
- Owner: TBD
- Complexity: Medium
- Subtasks:
  - Extract additional low-risk Router helpers (status formatting, reply helpers, config rendering) into dedicated modules.
  - Reduce direct state/audit/queue calls in Router where a helper already exists.
  - Add/update unit tests for the extracted helpers.

65) DONE - Add shutdown summary message (issue plan)
- Owner: TBD
- Complexity: Low
- Subtasks:
  - Send a shutdown summary message on disconnect/close that mirrors the startup summary context.
  - Log the same shutdown summary for operators.
  - Add tests to ensure the shutdown summary triggers once per session.

58) DONE - Consolidate audit helper calls (issue plan)
- Owner: TBD
- Subtasks:
  - Introduce a small audit helper/service for start/append/close patterns.
  - Replace direct audit calls in Router with helper usage.
  - Add tests to ensure audit entries are still written correctly.

59) DONE - Model selection and reporting (issue plan)
- Owner: TBD
- Subtasks:
  - Always report the effective model for a session when starting/resuming (and include it in any "started/resumed" acknowledgement messages).
  - Ensure model is included in status outputs (including per-session listings/pinned status where applicable).
  - Support changing the model per session via `!c model [session] <model-id>`.
  - If a job is currently running in the channel, `!c model ...` must be queued (not executed immediately) and take effect for subsequent runs.
  - Provide a way to list available models (from config) and show which model is currently effective for each session.
  - Provide a way to list available models by parsing output of the Codex `/models` command (and present them in a chat-friendly list).
  - Persist model choice per session and cover the behavior with unit tests (status text + start/resume reporting + queued model changes).

37) DONE - Telegram adapter completion
- Implement Telegram runtime wiring (polling/webhook) and response sending.
- Add Telegram config fields and validation.
- Expand `TELEGRAM.md` with real setup steps once wiring is implemented.

38) DONE - README integrations section
- Add an "Integrations" section in `README.md`.
- List supported/scaffolded integrations and link to docs (e.g., `DISCORD.md`, `SLACK.md`, `TELEGRAM.md`).

39) DONE - Audit log redaction toggle
- Add an optional config to redact secrets from audit logs (tokens/keys/passwords) before writing.
- Document the redaction option and any limitations.
- Add tests for redaction patterns.

40) DONE - DM command collision resolution
- Review DM admin command namespace vs per-repo DM commands (e.g., /bind, /repo, /use, /unbind).
- Define a precedence/namespace strategy to avoid collisions (admin-only prefix, reserved commands, or routing by adapter).
- Add a context status command that works in non-repo and repo context (e.g., /status or !c /status) to show current repo binding and active session.
- Document the resolution rules and add tests for ambiguous commands.

41) DONE - DM repo binding commands (prefix-only)
- Extend DM command parsing to support repo-binding commands with `!c` prefix: `bind`, `repo`, `use`, `unbind`, `status`.
- Define DM precedence: admin commands first, binding commands next, then prompt passthrough if bound.
- Store DM bound repo per user/channel and prefix DM responses with `[repo]`.
- Add tests for binding, unbinding, repo override, and collision handling.

42) DONE - Repo file upload/download support
- Support uploading files into repos and downloading files from repos via adapters.
- Define security constraints (path containment, size limits, allowed extensions) and audit logging.
- Add command UX (e.g., `!c upload`, `!c download`) and adapter-specific handling.

44) DONE - Telegram file upload/download support
- Replicate implicit upload flow for Telegram attachments with path prompt.
- Add `download` support for Telegram adapter via document sending.
- Document Telegram file transfer behavior and limits.

45) DONE - Platform thread context standardization
- Add platform thread/message identifiers to `MessageEvent`.
- Allow `ResponseSink` to target threads or reply-to message ids.
- Simulate threaded replies on Telegram with `reply_to_message_id` when no native thread id exists.

43) DONE - Improve operational logging
- Add structured log fields for routing decisions (platform, channel/chat, repo, session, command, DM binding changes).
- Log DM bind/unbind/use/repo events and destination routing decisions.
- Log adapter-specific events (Discord/Telegram) with context; include error details for failed routing.
- Review log verbosity and add config to tune (info/debug).

66) DONE - Enrich startup DM (issue plan)
- Owner: TBD
- Complexity: Low
- Subtasks:
  - When the bridge becomes ready, send a DM (or channel ping) that goes beyond “I’m alive!” with useful context for operators.
  - Include information such as current bot version/commit, configured default model + reasoning, repository code root, number of bound repos/sessions, active job counts, and optional rate-limit/token usage hints.
  - Keep the message concise but informative for debugging, and log the same summary locally.
 - Add tests/mocks to ensure the DM is sent once per session and include the extra context.

67) DONE - Add immediate Codex `/status` retrieval path (issue plan)
- Owner: TBD
- Complexity: High
- Subtasks:
  - Provide a Router helper that builds `/status` prompt args for an existing session without mutating thread or model state.
  - Run the prompt directly via the runner (bypassing the per-channel queue) and capture sanitized output lines for later parsing.
  - Add unit tests showing the immediate status call works while a session is still running.

68) DONE - Parse and format Codex `/status` output (issue plan)
- Owner: TBD
- Complexity: High
- Subtasks:
  - Parse `/status` output lines into a structured summary that tolerates box art and extra text.
  - Build a formatter that emits the key fields (`Model`, `Directory`, `Context window`, `5h limit`, `Weekly limit`) in stable lines for reuse in status updates and usage reports.
  - Cover the parser/formatter with unit tests including normal and degraded outputs.

69) DONE - Integrate parsed `/status` into `!c status` (issue plan)
- Owner: TBD
- Complexity: Medium
- Subtasks:
  - Include parsed `/status` lines (model/directory/context window/limits) in the `!c status` reply when the current session exists.
  - Trigger an immediate `/status` request without queuing and only append data when parsing succeeds.
  - Add tests covering the integrated output while jobs are running.
