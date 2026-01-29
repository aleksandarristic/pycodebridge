# Implementation Task List

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

---

## progress.log
- 2026-01-29: Repo initialized and .venv created (Python 3.14.2).
- 2026-01-29: Scaffolded Python package, config loader, util modules, state/audit/logging, and async codex runner skeleton.
- 2026-01-29: Added pending task notes for remaining porting work.
- 2026-01-29: Added DISCORD.md and refreshed README/AGENTS for the Python port.
- 2026-01-29: Added requirements.txt / requirements-dev.txt with pinned versions.
- 2026-01-29: Completed codex runner stderr streaming and exit status handling.
- 2026-01-29: Added typing keepalive and pinned status helpers for Discord wiring.
- 2026-01-29: Implemented core command routing, queue controls, and DM admin basics.
- 2026-01-29: Added repo bootstrap commands, GitHub clone parsing, and DM repo management.
- 2026-01-29: Added pytest coverage for core modules and helper logic.
- 2026-01-29: Added __main__ entrypoint and README run notes for editable installs.
- 2026-01-29: Added Windows-compatible process group handling for Codex interrupts.
- 2026-01-29: Added skills overview and instructions to use skills when appropriate.
- 2026-01-29: Added clean shutdown handling for Ctrl-C to avoid tracebacks.
- 2026-01-29: Switched to a typing context for reliable Discord typing indicators.
- 2026-01-29: Added PEP8 docstrings across Python modules.
- 2026-01-29: Split router handlers and helpers into dedicated modules.
- 2026-01-29: Added SessionService abstraction and unit tests for pending conflicts and active tracking.
- 2026-01-29: Introduced a command registry with generated help text and registry tests.
- 2026-01-29: Added transport-agnostic MessageEvent/ResponseSink contracts with Router refactor and transport tests.
- 2026-01-29: Added Discord adapter + transport config for MessageEvent/ResponseSink routing.
- 2026-01-29: Added Mermaid architecture diagram and doc references.
