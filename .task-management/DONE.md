# DONE

Rules:
- Keep original task ID when moving entries here.
- Keep entries in reverse chronological order (newest first).
- Include completion date and optional notes.

Format:
- [TASK-0000] Short task title.
  - Completed: YYYY-MM-DD
  - Notes: Optional

## Completed tasks

- [TASK-0028] Lean default prompt profiles for lower recurring token overhead.
  - Completed: 2026-04-29
  - Notes: Shortened built-in `start_prompt`/`spec_prompt` defaults, updated config examples with routine-vs-complex model/reasoning recommendations, and documented a lightweight prompt-profile pattern in README.

- [TASK-0029] Parallelize independent helper subprocesses on read-only command paths.
  - Completed: 2026-04-29
  - Notes: Parallelized independent subprocesses in `showchanges` and `updates` via `asyncio.gather` while preserving output ordering and existing error behavior; added targeted helper tests covering concurrent-start behavior.

- [TASK-0003] Compose + global skill defaults for cross-repo persistence (deferred).
  - Completed: 2026-04-29
  - Notes: Added Docker docs for user-level skill storage under `${CODEX_AUTH_HOST}/skills/...`, optional `codex.env.CODEX_HOME` override, restart/apply workflow, and guidance for coexistence with repo `AGENTS.md`.

- [TASK-0033] Command surface inventory and capability matrix.
  - Completed: 2026-04-29
  - Notes: Added `docs/COMMAND_SURFACE.md` with full channel/shortcut/DM command inventory and classification, and linked it from README for follow-on redesign tasks.

- [TASK-0024] Refactor `Router.handle_message` into focused phases to reduce nested branching and mixed responsibilities.
  - Completed: 2026-02-25
  - Notes: Split routing entry flow into explicit helper phases for attachment handling, pending upload replies, unprefixed prompt flow, and command flow; added shared repo-path error helper and preserved existing behavior with targeted router integration coverage.

- [TASK-0023] Centralize command authorization policy so `CommandSpec.auth` is the default source of truth.
  - Completed: 2026-02-25
  - Notes: Updated router TOTP policy decisions to derive default enforcement from command registry auth metadata while preserving subcommand-specific overrides (`options`, `lock`, `unlock status`, `git`, `gh`); added targeted regression test proving metadata-driven behavior.

- [TASK-0022] Consolidate shortcut command parsing so DM and repo-channel paths share one canonical parser core.
  - Completed: 2026-02-25
  - Notes: Added shared bang-shortcut normalizer and rewired router + DM shortcut handling to use it with explicit DM alias extensions; added targeted shortcut tests and verified DM/integration shortcut behavior.

- [TASK-0021] Remove dead command/DM helper code paths that no longer participate in runtime behavior.
  - Completed: 2026-02-25
  - Notes: Removed unused command registry constants/helpers and stale DM help helper path; validated command/DM test modules for no behavior regressions.

- [TASK-0014] Make repo bash scripts executable and update `update.sh` with auth checks and dry-run support.
  - Completed: 2026-02-25
  - Notes: Confirmed repo shell scripts are executable and `update.sh` includes `--dry-run`, `--check`, and warn-only post-start auth checks for Codex CLI and GitHub CLI with remediation guidance. Runtime execution validation is partially environment-blocked here due missing `docker`.

- [TASK-0013] Add comprehensive Codex CLI argument-ordering tests for runner arg-building contract.
  - Completed: 2026-02-25
  - Notes: Added matrix coverage for start/resume/resume-last arg construction across model/reasoning/approval/network permutations with order/flag assertions, while preserving existing strict order-contract tests.

- [TASK-0012] Remove compat retry fallback in router and fail fast on non-zero exit.
  - Completed: 2026-02-25
  - Notes: Removed stale resume compatibility retry/fallback mutation path from router run execution, deleted obsolete helper logic, and updated integration coverage to enforce single-attempt fail-fast behavior without argument rewriting.

- [TASK-0019] Enforce single-session-per-scope semantics with explicit expiry and stale-session controls.
  - Completed: 2026-02-25
  - Notes: Enforced one logical session per non-DM scope via scoped session resolution, preserved expired-session continue/new decision flow in scope, added `!c purge stale <ttl>` stale cleanup command, and aligned reset semantics with fresh-start behavior in scope. Updated command/docs and added targeted routing/integration coverage.

- [TASK-0018] Clarify state layout and add explicit session purge/reset flows.
  - Completed: 2026-02-25
  - Notes: Added explicit state/artifact map docs, introduced prefixed session artifact naming (`repo-<repo>__session-<session>`) across session logs/audit/session archives with compatibility handling, added `purge [session]` command that resets runtime/state and removes session artifacts, and added transport-agnostic `api_reset_session(..., purge=...)` hook for future web API integration with targeted coverage.

- [TASK-0017] Consolidate logging architecture with unified session JSONL streams and archival rotation.
  - Completed: 2026-02-25
  - Notes: Added consolidated per-session JSONL logs under `state.log_dir/session_jsonl/active/<channel>/<session>.jsonl`, wired key run/codex/output/error events, implemented mandatory `.tgz` archival for active logs older than 30 days into `session_jsonl/archive/...`, retained archives indefinitely, and updated tests/docs.

- [TASK-0016] Add top-level `!branch` command for branch + clean-state visibility.
  - Completed: 2026-02-24
  - Notes: Added a read-only `branch` command (`!c branch` and `!branch`) that summarizes current branch and working tree clean/not-clean status via git helper output, with targeted tests and docs updates.

- [TASK-0015] Universal channel/thread top-level `!<command>` support and stop/interrupt shortcut semantics.
  - Completed: 2026-02-24
  - Notes: Added generic top-level dispatch for all registered channel command names/aliases (`!command`/`!alias`), mapped `!stop` to `stop` (ESC then SIGINT), updated `interrupt` to ESC-only with aliases `int/esc/escape`, and added/updated targeted routing + help/model command tests and docs.

- [TASK-0011] Discord-only transport surface; remove Telegram/Slack wiring while preserving modular transport architecture.
  - Completed: 2026-02-24
  - Notes: Removed Telegram/Slack adapters and runtime wiring, deleted Telegram/Slack docs, simplified config validation to Discord-only transport, updated examples/architecture/testing docs, and adjusted targeted tests accordingly.

- [TASK-0007] Parametrize TOTP requirements in config for command groups.
  - Completed: 2026-02-24
  - Notes: Added nested `discord.totp` config with `command_groups` toggles for `git`, `gh`, and `high_risk`, preserved backward compatibility with legacy flat keys, and updated routing enforcement, docs, examples, and targeted tests.

- [TASK-0008] Broaden known `!git` command coverage (for example: `add`, `fetch`).
  - Completed: 2026-02-23
  - Notes: Added `add` and `fetch` support to git helpers, updated usage/help/docs, and added targeted tests for new routing plus unknown-subcommand rejection.

- [TASK-0001] Discord threads as isolated session contexts.
  - Completed: 2026-02-23
  - Notes: Finished thread room isolation hardening, legacy thread-key migration for state/runtime/queue, and regressions for thread stop + mention handling in threads.
