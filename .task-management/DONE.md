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

- [TASK-0062] Reconcile the `compact` option with the start-conflict prompt.
  - Completed: 2026-05-29
  - Notes: Surfaced `!compact – summarize prior context, then start fresh` in the start-conflict prompt (`handle_start`), so the `!compact`/`!cpt` shortcuts are discoverable. Fixed `build_compacted_session_prompt` lead-in wording ("the previous thread" instead of "previous expired thread") so it reads correctly for start-conflicts too. Added integration test covering `!compact` after a start-conflict (summarizes + starts fresh, no resume).

- [TASK-0061] Remove orphaned `session_expired` conflict handling in `handle_choose`.
  - Completed: 2026-05-29
  - Notes: Collapsed the dead `conflict.reason == "session_expired"` ternary in `codebridge/handlers/core.py` (replace path now always uses the configured start prompt). No flow produced that reason after 42e73ff; confirmed zero remaining references in `codebridge/` and `tests/`. Conflict/choose integration tests pass.

- [TASK-0060] Document new bang shortcuts (`!new`, `!compact`, `!cpt`) in README and COMMAND_SURFACE.
  - Completed: 2026-05-29
  - Notes: Added `!new` -> `choose new` and `!compact`/`!cpt` -> `choose compact` to `docs/COMMAND_SURFACE.md` conflict-resolution shorthand and to both README shortcut sections, matching `codebridge/commands/shortcuts.py`. Docs-only change; no code/tests affected.

- [TASK-0059] `_toml_string()` uses `json.dumps` for TOML string values.
  - Completed: 2026-05-14
  - Notes: Added ASCII guard — raises ValueError for non-ASCII input rather than silently producing a value that Codex CLI may mis-parse.

- [TASK-0058] Audit sequence sort relies on consistent zero-padding.
  - Completed: 2026-05-14
  - Notes: Changed sort key from `s.seq` (lexicographic) to `int(s.seq)` so a corrupted counter with inconsistent padding doesn't mis-sort entries.

- [TASK-0057] Single-token input to `parse_session_and_prompt` always treated as session name.
  - Completed: 2026-05-14
  - Notes: Changed `parse_session_and_prompt` to return `("", token)` for single-token input. Updated `_cmd_start` to extract session name via direct split (not the parser). Removed now-redundant single-token guard from `_cmd_resume`.

- [TASK-0055] Multi-file upload path traversal check weaker than single-file.
  - Completed: 2026-05-14
  - Notes: Replaced manual `startswith("..")` check with `pathutil.resolve_repo_file_path`, matching single-file upload validation and handling symlink resolution.

- [TASK-0054] Health endpoint body read silently truncated at 8192 bytes.
  - Completed: 2026-05-14
  - Notes: Changed `reader.read(8192)` to `asyncio.wait_for(reader.readline(), timeout=5.0)`; only the request line is needed, eliminating truncation and adding a 5s connection timeout.

- [TASK-0053] `!c git commit` auto-stages all tracked changes via `-a` without warning.
  - Completed: 2026-05-14
  - Notes: Changed `commit -am` to `commit -m`; requires explicit staging.

- [TASK-0052] Bare `!c audit` always errors instead of showing recent entries.
  - Completed: 2026-05-14
  - Notes: Replaced `if limit <= 0: error` with `limit = limit or 10`; no-arg invocation now defaults to 10 entries.

- [TASK-0051] `handle_updates` subprocess inherits full host environment including secrets.
  - Completed: 2026-05-14
  - Notes: Replaced `os.environ.copy()` + `setdefault` with a minimal `{"PATH": ..., "NPM_CONFIG_CACHE": ...}` dict, matching the allowlist pattern used by the Codex runner.

- [TASK-0050] Startup DM sent to all `allowed_user_ids` when no admin list is configured.
  - Completed: 2026-05-14
  - Notes: Dropped `or cfg.allowed_user_ids` fallback in both `on_ready` and `_send_shutdown_summary`; startup/shutdown DMs now only fire when `dm_admin_user_ids` is explicitly set.

- [TASK-0049] `repo_busy()` checks channel-wide activity instead of per-repo activity.
  - Completed: 2026-05-14
  - Notes: Rewrote to iterate `ch.sessions.items()` and check `get_active(channel_id, sess_name)` plus filter snapshot statuses by session name.

- [TASK-0046] Repo deletion fails on symlinked subdirectories, leaving partial state.
  - Completed: 2026-05-14
  - Notes: Replaced manual `os.walk`/`os.rmdir` with `shutil.rmtree(repo_path)`; added `import shutil`.

- [TASK-0044] Fire-and-forget `_waiter` task can be GC'd before `on_exit` runs.
  - Completed: 2026-05-14
  - Notes: Added module-level `_background_tasks` set; task is added on creation and discarded via `done_callback`.

- [TASK-0043] Blocking `os.write()` on PTY fd can freeze the entire event loop.
  - Completed: 2026-05-14
  - Notes: Wrapped with `loop.run_in_executor(None, os.write, self._stdin_fd, data)`.

- [TASK-0042] `!c ps` crashes with AttributeError on every invocation.
  - Completed: 2026-05-14
  - Notes: Removed stale `{s.command}` reference from `handle_ps` format string; `JobStatus` has no `command` field.

- [TASK-0041] Clarify misleading double `_purge_session_artifacts` call.
  - Completed: 2026-05-14
  - Notes: Consolidated into a single call preceded by two `asyncio.sleep(0)` yields; added comment explaining the yields are needed to let exit callbacks flush before deletion.

- [TASK-0040] Remove redundant `.git` filter in `_suggest_upload_paths`.
  - Completed: 2026-05-14
  - Notes: Removed `.git` from the explicit exclusion set; already excluded by the `startswith(".")` check above it.

- [TASK-0039] Replace `assert` statements in production code with proper guards.
  - Completed: 2026-05-14
  - Notes: Replaced all three: `codex.py` returns a `RuntimeError` from the reader if stdout is absent; `router.py` lock-extend raises `RuntimeError` if `ttl_seconds` is None; reset-all handler uses an `isinstance` `if`-guard instead of asserting.

- [TASK-0038] Remove dead validation branch in `_validate_repo_name`.
  - Completed: 2026-05-14
  - Notes: Removed the unreachable second condition; the regex already excludes all the characters it checked for.

- [TASK-0037] Deduplicate bool-parsing logic in `state.py`.
  - Completed: 2026-05-14
  - Notes: Removed `_BOOL_TRUE`/`_BOOL_FALSE` sets and rewrote `_normalize_bool` to delegate to `parse_bool` from `util/coerce.py`, returning `None` on `ValueError`.

- [TASK-0036] Fix missing `import re` in `audit.py`.
  - Completed: 2026-05-14
  - Notes: Added `import re`; fixes `Redactor` crash and all three `test_audit_redaction` test failures.

- [TASK-0035] Command information architecture, naming, and help-system rewrite.
  - Completed: 2026-05-07
  - Notes: Reorganized help and docs around a golden path, limited promoted shortcuts to the intended active-run shorthands, and aligned command docs with the redesigned surface.

- [TASK-0034] Command model redesign around a minimal core workflow.
  - Completed: 2026-05-07
  - Notes: Added explicit command-model metadata and documented the minimal core workflow and namespace/surface structure for follow-on command cleanup.

- [TASK-0032] Async/batched session JSONL logging for high-output runs.
  - Completed: 2026-05-07
  - Notes: Batched hot session JSONL writes while preserving immediate flush behavior for terminal and error events, with targeted logging coverage.

- [TASK-0030] Add in-memory state caching for hot read paths.
  - Completed: 2026-05-07
  - Notes: Added validated in-memory snapshot reuse for hot `state.load()` paths with invalidation on local writes and regression coverage for external changes.

- [TASK-0031] Reduce reply-path overhead from repeated chunking and nested send loops.
  - Completed: 2026-05-07
  - Notes: Centralized chunk ownership in the reply path so helpers and contextual sinks stop pre-chunking the same output multiple times.

- [TASK-0002] Final-message ordering hardening for run lifecycle output.
  - Completed: 2026-05-07
  - Notes: Added terminal-event ordering guards so late progress output is suppressed after run completion, with regressions for delayed post-exit output and budget-notice ordering.

- [TASK-0009] Intermittent `!reset` top-level alias is not parsed as `!c reset`.
  - Completed: 2026-05-07
  - Notes: Hardened explicit top-level `!reset` shortcut parsing and added direct parser plus integration coverage for channel and thread scopes.

- [TASK-0010] Discord thread bootstrap message leaks into parent channel on thread creation.
  - Completed: 2026-05-07
  - Notes: Fixed first-message thread context and reply targeting so Discord thread bootstrap output stays inside the created thread, with regression coverage.

- [TASK-0005] Knowledge shortcuts/macros for repeatable repo workflows.
  - Completed: 2026-05-07
  - Notes: Added a bounded `!c workflow` / `!c wf` command with built-in `inspect`, `fix`, `review`, and `ship` macros that expand into standardized Codex prompts via the normal resume path, plus help/docs and targeted routing coverage.

- [TASK-0026] Budget-aware token guardrails for oversized runs and sessions.
  - Completed: 2026-04-29
  - Notes: Extended `!c budget` with `session` and `run` scopes, added session-hard pre-run blocking, surfaced run/session soft and hard notices during and after runs, recorded per-session last-run token totals, and updated status/docs plus targeted budget integration coverage.

- [TASK-0025] Session compaction and idle-expiry defaults for token control.
  - Completed: 2026-04-29
  - Notes: Enabled a 4-hour default session idle TTL, added `!c choose compact` for expired-session restarts from a concise summary instead of full thread history, cleared stale thread ids before fresh-start paths, and added targeted parser/config/integration coverage for compact restart behavior.

- [TASK-0027] Cache-first model listing to avoid unnecessary Codex `/model` runs.
  - Completed: 2026-04-29
  - Notes: `!c models` now serves cached model data by default, supports explicit refresh (`refresh`, `--refresh`, `-r`) to re-query Codex, and includes targeted tests for cache-hit and refresh behavior.

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
