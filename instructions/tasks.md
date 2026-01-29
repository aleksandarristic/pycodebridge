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

6) IN PROGRESS - Codex runner
- Async subprocess runner for `codex exec --json ...`.
- Parse JSONL, extract agent messages and thread_id.
- Provide stop (ESC), interrupt (SIGINT), kill controls.
- Allow per-session model overrides.
- PENDING: connect stderr stream to audit logger and capture exit status for router.

7) DONE - Message formatting utilities
- ANSI/control stripping.
- Chunking to Discord size.
- User-input prompt detection and `Codex asks:` prefix.
- Diff fence rendering where appropriate.

8) DONE - Per-channel queue and job controls
- Serialized processing per channel+session.
- `ps`, `cancel`, `rerun` with job IDs.
- Track active job + queued positions.

9) IN PROGRESS - Discord bot wiring
- discord.py client with required intents.
- Message handler for channels and DMs.
- Typing indicator keepalive while running.
- PENDING: typing indicator keepalive task and status message management.

10) TODO - Command routing
- Implement all commands from spec (start/resume/choose/stop/kill/quit/etc.).
- Git helpers with safe flag allowlist and timeouts.
- Repo helpers: showrepo/showchanges/tests.
- DM admin commands gated by config.
- “I’m sorry, Dave...” wrapper for forbidden/invalid commands.
- Session limit (max 3) and sticky session selection.

11) TODO - Repo bootstrap commands
- `createrepo`, `clonerepo`, `copyrepo` with containment rules.
- Optional AGENTS.md template seeding.
- `spec` flow to generate instructions/spec.md + tasks.

12) DONE - Logging
- stdlib logging, human-readable format.
- Log to stdout and rotating file in log_dir.

13) TODO - Tests
- Pytest suite mirroring Go tests: config/path/state/audit/router/queue/codex.
- Add small integration tests with fake codex output.

14) DONE - Docs
- README with setup, config reference, commands, DM admin notes.
- DISCORD.md with bot intents and invite setup.

15) TODO - Packaging/runtime ergonomics
- Add `__main__.py` or console script entrypoint.
- Add `pip install -e .` and `python -m cmd.bridge` run notes.

16) TODO - Windows/macOS compatibility pass
- Verify path expansion, file locks, and signal handling.
- Replace SIGINT-only logic with cross-platform handling where needed.

17) DONE - Requirements files
- Add `requirements.txt` and `requirements-dev.txt` with pinned versions.
- Keep dev requirements installing into `.venv`.

---

## progress.log
- 2026-01-29: Repo initialized and .venv created (Python 3.14.2).
- 2026-01-29: Scaffolded Python package, config loader, util modules, state/audit/logging, and async codex runner skeleton.
- 2026-01-29: Added pending task notes for remaining porting work.
- 2026-01-29: Added DISCORD.md and refreshed README/AGENTS for the Python port.
- 2026-01-29: Added requirements.txt / requirements-dev.txt with pinned versions.
