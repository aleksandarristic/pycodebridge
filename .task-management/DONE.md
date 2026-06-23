# DONE

Rules:
- Keep original task ID when moving entries here.
- Keep entries in reverse chronological order (newest first).
- Include completion date and optional notes.

Format:
- [TASK-0000] Short task title.
  - Completed: YYYY-MM-DD

- [TASK-0090] Gemini streamed output preserves ask prefix across split chunks.
  - Completed: 2026-06-23
  - Notes: Added buffered-output prefixing so a later chunk that reveals a split prompt can prepend `Gemini asks:` to the already-buffered first chunk before flushing. Added coalescer regression coverage for split Gemini prompt output and empty-buffer behavior.

- [TASK-0110] Dispatch parser ignores `@agent` substrings inside emails and words.
  - Completed: 2026-06-23
  - Notes: Tightened dispatch mention parsing to require standalone mention boundaries, preserving emails, identifiers, and hyphenated tokens that contain known agent names. Added parser regression coverage for email, word-boundary, hyphenated, and punctuation cases.

- [TASK-0109] Repeated dispatches create fresh worker branches.
  - Completed: 2026-06-23
  - Notes: Added unique run IDs to worker branch names so repeated dispatches for the same agent fork from the current task branch instead of reusing stale worker state. Updated dispatch docs/examples and added regression coverage for repeated same-agent dispatch.

- [TASK-0108] Dispatch handoff preserves uncommitted worker edits.
  - Completed: 2026-06-23
  - Notes: Added dirty-worktree preservation after successful agent runs: uncommitted edits are staged and committed on the handoff branch before the worktree is removed. Updated real-git orchestrator coverage so an agent that only writes a file still leaves that file on the worker branch and reports changed files.

- [TASK-0111] Dispatch preserves worker branch handoff instead of auto-merging.
  - Completed: 2026-06-23
  - Notes: Removed automatic successful-worker merges into the task branch and restored the handoff model where worker branches remain separate until explicit promotion. Updated orchestrator regression coverage to verify committed worker changes stay on the worker branch while the task branch remains unchanged.

- [TASK-0107] Worktree cleanup unregisters external `base_dir` worktrees.
  - Completed: 2026-06-23
  - Notes: Resolved linked worktree owners from the worktree `.git` file before falling back to sibling repo discovery, so external `worktrees.base_dir` cleanup runs `git worktree remove` against the correct repo. Added regression coverage proving external worktree removal clears `count_for_repo()` immediately and leaves no prunable entry.

- [TASK-0106] Failed dispatch close preserves the active task branch for retry.
  - Completed: 2026-06-23
  - Notes: Changed `TaskCloser.close()` to clear task state and clean worker branches only after PR creation or merge succeeds. Updated regression coverage so failed close attempts keep the task branch and skip cleanup.

- [TASK-0105] Dispatch worker changes are merged into the task branch closed by `!c done`.
  - Completed: 2026-06-23
  - Notes: Merged successful worker branches back into the persisted task branch after worker runs and before dispatch completion, reporting merge conflicts as failed agent results. Added unit coverage for merge calls/failures and a real-git regression proving worker commits are present on the task branch closed by `!c done`.

- [TASK-0104] Dispatch documentation and worked examples.
  - Completed: 2026-06-23
  - Notes: docs/dispatch.md reference, three examples under docs/examples/, README Multi-agent dispatch section.

- [TASK-0103] Task close command: `!c done` with PR and merge modes.
  - Completed: 2026-06-23
  - Notes: TaskCloser (closer.py) with _open_pr, _merge, _cleanup_worker_branches; wired into router as "done" command; constructed alongside Orchestrator in cmd/bridge.py.

- [TASK-0102] Dispatch output: per-agent status messages and aggregate summary.
  - Completed: 2026-06-23

- [TASK-0101] Orchestrator flow: task branch + sequential/parallel dispatch.
  - Completed: 2026-06-23

- [TASK-0100] DispatchConfig: dataclass + YAML loading + validation.
  - Completed: 2026-06-23

- [TASK-0099] Dispatch parser: @agent extraction and fan-out detection.
  - Completed: 2026-06-23

- [TASK-0098] Docs: `config.example.yaml`, `config.docker.example.yaml` + README worktree section.
  - Completed: 2026-06-23

- [TASK-0097] Wire `WorktreeManager` into router/coordinator: create on run-start, remove on exit.
  - Completed: 2026-06-23

- [TASK-0096] `SessionState.worktree_path` field + JSON persistence.
  - Completed: 2026-06-23

- [TASK-0095] `services/worktree.py`: `WorktreeManager` with create/remove/prune.
  - Completed: 2026-06-23

- [TASK-0094] `WorktreeConfig` dataclass + YAML loading + validation in `config.py`.
  - Completed: 2026-06-23
  - Notes: Optional

## Completed tasks

- [TASK-0092] Rename channel prefix from codex- to code-.
  - Completed: 2026-06-22
  - Notes: DEFAULT_CHANNEL_REGEX → ^code-. All user-facing strings, docs (README, DISCORD.md, DOCKER.md), and example configs updated. Tests updated: channel names, hardcoded regex patterns, assertion strings. Added !c renamechannels/rc <old-prefix> <new-prefix> [--preview] DM admin command for live migration.

- [TASK-0093] Surface tool calls and thinking blocks during long Claude runs.
  - Completed: 2026-06-11
  - Notes: Extended `NormalizedEvent` with `tool_calls` and `thinking` fields. `ClaudeBackend.parse()` now extracts `tool_use` and `thinking` content blocks from `assistant` events. `on_jsonl` relays a `[ToolName] \`input\`` label for every tool call (always, subject to `relay_output`), and thinking text gated on `show_reasoning_details` (default on). A module-level `_format_tool_call_label` helper formats the most descriptive input field per tool. New tests in `tests/test_claude_backend.py` cover extraction of all three block types.

- [TASK-0091] Command to clear all but the last pinned message in a channel.
  - Completed: 2026-06-11
  - Notes: Added `!c unpin` (in-channel) and `!c unpin` (DM admin) command. In-channel variant unpins all but the most recently pinned message in the current channel. DM admin variant iterates all guild text channels matching `channel_name_regex` and does the same for each. Guild channel access is wired via `Router.set_guild_text_channels_fn`, set by `BridgeClient.__init__`. Zero/one-pin channels are no-ops with a message. Targeted tests: `tests/test_unpin_command.py` (12 tests covering unit and integration paths for both surfaces).

- [TASK-0090] Auto-steer plain messages to the active session.
  - Completed: 2026-06-11
  - Notes: Plain messages in a channel with exactly one running session are now written directly to that session's stdin instead of being silently queued as the next resume prompt. Multi-session channels get a disambiguation error pointing to `!s:<session> <text>`. Zero-session channels fall through to the existing allow-plain/resume path unchanged. Targeted tests: `tests/test_integration_harness.py` — `test_integration_plain_message_auto_steers_single_active_session`, `test_integration_plain_message_with_multiple_active_sessions_is_rejected`, `test_integration_plain_message_with_no_active_session_falls_through_to_resume`.

- [TASK-0086] Thread messages silently dropped when parent channel not in Discord cache.
  - Completed: 2026-06-11
  - Notes: Discord message handling now enriches thread events by fetching missing parent channel metadata before routing, and event normalization can also recover parent names from a guild cache lookup. This preserves parent-channel repo mapping when `Thread.parent` is absent after restarts or cache misses. Targeted tests: `tests/test_router_contextual_sink.py`, `tests/test_discord_bot.py`, `tests/test_integration_harness.py::test_integration_discord_thread_uses_parent_repo_mapping_and_room_scope`, `tests/test_integration_harness.py::test_integration_discord_sibling_threads_are_isolated`, `tests/test_integration_harness.py::test_integration_discord_thread_stop_rekeys_legacy_thread_scope`.

- [TASK-0089] Successful agent runs can finish with no user-visible terminal message.
  - Completed: 2026-06-11
  - Notes: Successful runs that relay zero assistant output now always send a terminal "no assistant message" notice with log guidance, independent of `run_completion_min_seconds`; regular short runs with output remain quiet as before. Targeted tests: `tests/test_integration_harness.py::test_run_codex_success_without_output_sends_terminal_notice`, `tests/test_integration_harness.py::test_integration_run_completion_summary_suppressed_for_short_run`, `tests/test_integration_harness.py::test_integration_late_progress_is_suppressed_after_terminal_summary`, `tests/test_integration_harness.py::test_integration_budget_notice_precedes_terminal_summary`.

- [TASK-0088] Final stream result does not stop heartbeat when the CLI process lingers.
  - Completed: 2026-06-11
  - Notes: Router now treats backend `result` stream events as terminal lifecycle signals, marks the run relay terminal so heartbeat stops, and races process wait against a short final-result grace window. If the process lingers past the grace period, the bridge kills/cancels it and finishes through the normal success/failure path. Targeted tests: `tests/test_integration_harness.py::test_run_codex_final_result_kills_lingering_process`, `tests/test_integration_harness.py::test_run_codex_surfaces_claude_usage_limit_result_even_on_zero_exit`, `tests/test_integration_harness.py::test_run_codex_surfaces_claude_usage_limit_stderr`, `tests/test_claude_backend.py`.

- [TASK-0087] Unsupported configured default Codex model is reported as a stale session override.
  - Completed: 2026-06-11
  - Notes: Session state no longer persists configured Codex model/reasoning defaults as session overrides during thread updates; effective defaults still resolve at run time. Unsupported-model guidance now detects when the rejected model is `cfg.codex.model` and tells the operator to change or clear config instead of suggesting `!model default` / `!reset default`. Targeted tests: `tests/test_session_service.py`, `tests/test_integration_harness.py::test_run_codex_wraps_duplicate_unsupported_model_jsonl_error`, `tests/test_integration_harness.py::test_run_codex_unsupported_configured_default_points_to_config`, `tests/test_integration_harness.py::test_run_codex_wraps_unsupported_model_stderr_error`.

- [TASK-0085] Wrong backend error on stop command after backend switch.
  - Completed: 2026-06-11
  - Notes: Replaced the hardcoded "No running Codex process." string in handle_stop, handle_interrupt, handle_kill, and handle_quit with a backend-agnostic "No agent running in session 'X'." message. Added a hint listing other active sessions in the channel so the user can identify where the real run is (e.g. the thread session vs the default session). Docstrings updated to remove Codex-specific language.

- [TASK-0084] Main conversation session hangs while heartbeat continues.
  - Completed: 2026-06-11
  - Notes: Root cause: _run_heartbeat checked `if run_state is not None and run_state.is_terminal` — when the run relay was cleared by on_exit (called from the background _waiter task), run_state became None and the condition was False, so the heartbeat kept looping. Fixed by changing to `if run_state is None or run_state.is_terminal` so the heartbeat stops when the relay state is gone (i.e. the run has ended). This was bundled into the TASK-0083b commit since both changes are in _run_heartbeat.

- [TASK-0083b] Heartbeat ping message shows agent, model, and effort.
  - Completed: 2026-06-11
  - Notes: Extended _run_heartbeat signature with backend_name, model, reasoning_effort. Updated the single call site in run_codex to derive backend_name from type(_backend).__name__. New format: "Claude (claude-sonnet-4-6) working for 2m with high effort." — model parens omitted when not set, effort clause omitted for Gemini and when unset, session clause omitted for the default session.

- [TASK-0083] `!agent`, `!model`, `!effort` with no args show current session selection.
  - Completed: 2026-06-11
  - Notes: Added no-arg display path to _cmd_model, _cmd_agent, and _cmd_effort. Each command now shows the current effective value with "session override" or "configured default" label. !c effort for Gemini sessions replies "not applicable" instead of a forbidden error. A lone token that doesn't look like a model id / backend / effort level is treated as a session name for display. No session is created as a side-effect.

- [TASK-0082] Revisit Gemini backend because Gemini is not working.
  - Completed: 2026-06-10
  - Notes: Root cause was a silent failure when a configured/unavailable model is rejected by the API — the run ended with no user-facing message. Fixed by parsing the direct `error` object in the stream-json `result` event and adding backend-aware router detection for Gemini model-not-found (`ModelNotFoundError` / `Requested entity was not found` / `code: 404`), surfacing an actionable reply that points to `!models` / `!model <id>`. Validated end to end against real `gemini 0.45.2` (OAuth) in a temp git repo: start, resume-by-id (context carried across turns), and resume-latest all returned `result/status=success` with exit 0; an invalid `-m` run reproduced the failure (exit 1) emitting a `result/status=error` with `error.type=unknown` on stdout and `ModelNotFoundError: Requested entity was not found. code: 404` on stderr. Fed the captured real lines back through `GeminiBackend.parse()` and `_GEMINI_MODEL_NOT_FOUND_RE` to confirm they match the existing fixtures. Live stream-json shape matches `.task-management/TASK-0020-gemini-stream-json-schema.md` (default model `gemini-3-flash-preview`), so no schema refresh was needed. Full suite green.

- [TASK-0081] Surface Claude usage-limit exhaustion immediately.
  - Completed: 2026-06-09
  - Notes: Added backend-aware friendly error detection for Claude usage-limit messages from stream-json result errors and stderr. Captured friendly errors now produce a user-facing reply even when the CLI exits with code 0, avoiding silent completion after typing clears. Verified against local Claude Code 2.1.169 stream-json output: a `rate_limit_event`, assistant text `You've hit your session limit · resets ...`, and an `is_error` result with `api_error_status: 429`; the UTC reset time is parsed and shown as Central European local time. Focused router coverage uses that wording plus a stderr limit case.

- [TASK-0075] Require TOTP for DM reset-all.
  - Completed: 2026-06-09
  - Notes: DM admin `reset all` now requires TOTP before the yes/no confirmation when TOTP is enabled, while preserving non-admin rejection and cancellation behavior; added focused DM/integration coverage.

- [TASK-0077] Make model and effort default clearing explicit.
  - Completed: 2026-06-09
  - Notes: Added explicit session override clearing for model and reasoning effort. `!effort default` clears effort, `!model default` clears the current session model override, and `!model <id> default` applies a model while clearing reasoning; updated help/docs and Codex/Claude tests.

- [TASK-0078] Rework limited helper subprocess output draining.
  - Completed: 2026-06-09
  - Notes: `run_limited_command()` now keeps draining stdout/stderr after the retained-output cap, waits for process and reader completion under one timeout, and appends a truncation marker; added large stdout/stderr, timeout, and non-zero exit tests.

- [TASK-0079] Guard public health endpoint binds.
  - Completed: 2026-06-09
  - Notes: Health server binds now reject non-loopback hosts by default, with explicit `runtime.health_allow_public` opt-in; updated config loading/rendering, example config, README, and health/config tests.

- [TASK-0076] Harden upload persistence against aggregate-size abuse and symlink races.
  - Completed: 2026-06-09
  - Notes: Added `files.max_upload_total_mb` and `files.max_upload_count` batch limits while preserving per-file `files.max_upload_mb`. Upload saves now write to a repo-local temporary file, verify the temp file remains regular, recheck parent containment/no-symlink state, and finalize with an exclusive hard link so existing files are not overwritten. Existing final-path symlinks are rejected, symlink parent directories are rejected, and a file created during save causes unique-name finalization rather than overwrite. Updated config example and README. Targeted tests: `tests/test_dm_upload_download_gating.py`, `tests/test_config.py::test_load_config_upload_batch_limits`, `tests/test_dm_binding.py::test_dm_pending_upload_response_short_circuits`, `tests/test_integration_harness.py::test_totp_required_for_config_tests_download_logs_and_upload`.

- [TASK-0074] Apply redaction consistently to session JSONL and Codex error logs.
  - Completed: 2026-06-09
  - Notes: `AuditLogger` exposes its configured `Redactor`; `Router` passes that same redactor into `SessionJsonlLogger` and applies it before writing `codex_errors.log`. Session JSONL redacts all event payloads before buffering/writing, and Codex error-log payloads are redacted before both the raw error log and mirrored `codex.error` session event. Custom redaction patterns are additive with built-in secret/TOTP patterns. `audit.redact` remains opt-in. Targeted tests: `tests/test_audit_redaction.py`, `tests/test_session_jsonl.py`, `tests/test_integration_harness.py::test_router_redacts_codex_error_and_session_jsonl_logs`, `tests/test_integration_harness.py::test_router_writes_codex_error_log`.

- [TASK-0073] Sanitize TOTP before any DM audit write.
  - Completed: 2026-06-09
  - Notes: Added `Router.sanitize_totp_for_logs()` and applied it in `dm_audit_start()` so DM request metadata masks `--totp` values before opening the audit entry, including normalized bare `unlock <code>` syntax. Default redaction patterns now cover `--totp <code>`, `--totp=<code>`, and `totp=<code>` forms, including list-shaped CLI args where the code is a separate argument. Targeted tests cover DM unlock valid/replay paths and invalid high-risk DM admin create/delete paths.

- [TASK-0080] Wrap stale unsupported-model Codex errors with actionable user guidance.
  - Completed: 2026-06-09
  - Notes: Router failure handling now detects Codex unsupported-model errors from parsed JSONL error events and stderr JSON lines, suppresses duplicate raw JSON relay, and returns a single actionable message naming the affected session/model with `!model` and `!reset` recovery commands. Existing non-model non-zero exits still include the exit code and last stderr. Targeted tests: `tests/test_integration_harness.py::test_run_codex_wraps_duplicate_unsupported_model_jsonl_error`, `tests/test_integration_harness.py::test_run_codex_wraps_unsupported_model_stderr_error`, `tests/test_integration_harness.py::test_run_codex_fails_fast_on_usage_error_without_compat_retry`, `tests/test_integration_harness.py::test_integration_auto_relays_plain_reply_when_codex_waits_for_input`, `tests/test_integration_harness.py::test_integration_wait_command_reports_pending_input`.

- [TASK-0020] Add Gemini CLI backend.
  - Completed: 2026-06-09
  - Notes: `GeminiBackend` in `agents/gemini.py` — builds `gemini -o stream-json --skip-trust` invocations; `-p <prompt>`, `--resume <session_id>`, `--resume latest`, `-m <model>`, `--approval-mode <mode>`. `parse()` maps `init`→`init`, `message(role=assistant)`→`message` (content field), `error` event stashed in `_last_error_msg`, `result`→`result` (stats as usage + error from stash); everything else `None`. `GeminiConfig` dataclass in `config.py` (binary, approval_mode, model, env). `"gemini"` in `KNOWN_BACKENDS` and `build_backend()`. Gemini auth vars (`GEMINI_API_KEY`, `GOOGLE_APPLICATION_CREDENTIALS`, `GOOGLE_CLOUD_PROJECT`, `GEMINI_CLI_TRUST_WORKSPACE`) added to `_merge_env` allowlist. Schema documented in `.task-management/TASK-0020-gemini-stream-json-schema.md`. 25 focused tests in `tests/test_gemini_backend.py`.

- [TASK-0071] Add Claude Code CLI backend.
  - Completed: 2026-06-09
  - Notes: `ClaudeBackend` in `agents/claude.py` — builds `claude -p --output-format stream-json --verbose` invocations; `build_start_args`, `build_resume_args` (`--resume`), `build_resume_last_args` (`--continue`); `--model`, `--effort`, `--add-dir`, `--permission-mode`/`--dangerously-skip-permissions` flags. `parse()` maps `system/init`→`init`, `assistant`→`message` (text blocks only), `result`→`result` (usage + error); everything else returns `None`. `ClaudeConfig` dataclass in `config.py` (binary, permission_mode, model, effort, env). `"claude"` registered in `KNOWN_BACKENDS` and `build_backend()` in `factory.py`. Claude auth vars (`ANTHROPIC_API_KEY`, `CLAUDE_CODE_OAUTH_TOKEN`, `CLAUDE_CONFIG_DIR`) added to `_merge_env` allowlist in `base.py`. Stream-json schema documented in `.task-management/TASK-0071-claude-stream-json-schema.md`. 24 focused tests in `tests/test_claude_backend.py`.

- [TASK-0070] Per-session agent backend selection with `!agent` command.
  - Completed: 2026-06-09
  - Notes: `AgentConfig.default_backend` added to config; `SessionState.backend` field (backward-compat with existing state files); `SessionService.session_backend`/`set_session_backend` (switch clears thread_id, resets model/effort); `Router.backend_for` returns `self.runner` for default (test-injectable), builds fresh instance only on explicit override; `_session_backend_from_state` helper in `handlers/core.py`; all `handle_start`/`resume`/`spec`/`choose` call sites route through resolved backend; new `!c agent [session] <backend>` command mirroring `!c model` flow with queuing/validation/reset notification; `run_codex` accepts optional `backend` param; `on_jsonl` uses backend for parse(); `run.start` session log entry includes backend class name. 17 focused tests in `tests/test_agent_backend_selection.py`. Full suite green.

- [TASK-0072] `!reset`/`!c reset` raises `TypeError` when a session has an active process.
  - Completed: 2026-06-09
  - Notes: `control_reset_session` called `await proc.kill()` at `router.py:1656`, but `Process.kill` (`agents/base.py:94`) is synchronous and returns `None`, so awaiting it raised `TypeError`. Dropped the `await` to match the sibling stop path (`router.py:1610`). The 3 previously-failing `tests/test_integration_harness.py` reset tests now pass; full suite green.

- [TASK-0069] Abstract the agent backend behind a common interface.
  - Completed: 2026-06-08
  - Notes: New `codebridge/agents/` package. `agents/base.py` owns the backend-agnostic plumbing moved verbatim from `codex.py` (`Process`, `Options`, `_merge_env`) plus the shared streaming `AgentBackend.run` loop, the `AgentBackend` ABC (`build_start_args`/`build_resume_args`/`build_resume_last_args`/`parse`), and the `NormalizedEvent` seam (`type`, `session_id`, `texts`, `usage`, `error`, `raw`). `run` now calls `self.parse(line)` and uses `evt.texts` + a per-backend `ask_prefix` (Codex = "Codex asks:") instead of module-level `parse_event`/`display_texts`. `codex.py` keeps only Codex specifics (`Event`/`parse_event`/`agent_texts`/`display_texts` + arg grammar) as `CodexBackend(AgentBackend)`, whose `parse` delegates to the module-level `parse_event` (so the monkeypatch in `test_runner_parses_each_stdout_line_once` still works); `Runner = CodexBackend` alias preserves existing construction. `agents/factory.py` `build_backend(cfg, name)` (codex only for now). Consumers updated: `router.py` (`evt.texts`, `self.runner.parse` fallback, `AgentBackend`/`NormalizedEvent` types), `routing/helpers.py` (`usage_from_event` typed on `NormalizedEvent`), `cmd/bridge.py` uses `build_backend(cfg)`. Test doubles `_FakeRunner`/`_LateOutputRunner` gained `parse = CodexBackend.parse` (they feed JSONL the router parses on the fallback path). Pure refactor, no behavior change. Full suite green except the 3 known pre-existing `await proc.kill()` failures (sync `Process.kill`), which fail identically on HEAD and are unrelated. Selection/`!agent` command is TASK-0070; Claude backend is TASK-0071.

- [TASK-0067] Choose and set a default `codex.model_reasoning_effort`.
  - Completed: 2026-05-30
  - Notes: Product decision taken by user ("use decision 1" = first option = `minimal`; global scope, no per-repo config). Set `model_reasoning_effort: "minimal"` in `config.yaml` and `config.example.yaml` (with comments explaining the token/quality tradeoff and the per-session override). Documented the default + override in README codex-config section. The dataclass default stays `""` (= Codex built-in default when unconfigured); the runner mechanism (`_reasoning_args` -> `-c model_reasoning_effort=...`) and the `!c model [session] <id> [reasoning]` override were already in place and tested. Added `test_load_config_codex_model_reasoning_effort` covering yaml parsing. NOTE for user: `minimal` is the lowest-token setting and may reduce answer quality on harder tasks — bump to `low`/`medium`/`high` in config or per session if needed.

- [TASK-0065] Coalesce Codex output relay into batched Discord sends.
  - Completed: 2026-05-30
  - Notes: Added `_OutputCoalescer` (in `router.py`): buffers streamed output and flushes when it nears `max_discord_message_chars`, after an idle window, or on explicit flush. `run_codex` creates one per run and flushes it in the post-`wait()` `finally` (before the completion summary / error reply, so output stays ordered ahead of "Run complete"). `on_jsonl` routes relay through a new `_emit_output` helper that coalesces when a coalescer is supplied and force-flushes on awaiting-input ("Codex asks:") so prompts are never delayed; direct/test `on_jsonl` calls (no coalescer) still relay immediately. Window is a static config knob `runtime.output_flush_seconds` (default 0.4; 0 disables), documented in `config.example.yaml`. Chunking at `max_discord_message_chars` preserved; audit/session-jsonl logging still reflects what is actually sent. Fixed a timer self-cancellation case (idle-timer-triggered flush clears its own handle before flushing). Added `tests/test_output_coalescer.py`. Integration/model/codex suites pass (minus the 3 pre-existing `await proc.kill()` failures).

- [TASK-0064] Single-parse the Codex JSONL stream path.
  - Completed: 2026-05-30
  - Notes: `codex.py` `_read_stdout` now parses each stdout line once (`parse_event`) and forwards the parsed `Event` to `on_jsonl(line, evt)`; thread id is read from `evt.thread_id` and the `on_output` block is guarded so it only runs when a consumer is registered. Removed the now-dead `extract_thread_id`. `router.on_jsonl` reuses the supplied `evt` (parses lazily only when omitted, preserving direct test calls). Output tracking moved off the redundant `_capture_output`/`on_output` path into a local `_OutputTracker` updated by `on_jsonl` (race-free vs `on_exit` clearing run state); `run_codex` now wires the caller's `on_output` directly (model-list path unchanged). Dropped the redundant re-strip in `_relay_output_text` (callers pre-strip). Net: JSON lines parsed once and stripped once before relay. Added `test_runner_parses_each_stdout_line_once`. Note: 3 pre-existing integration failures (`await proc.kill()` on sync `Process.kill`) are unrelated and fail identically on HEAD.

- [TASK-0063] Expired-session recovery policy: auto-compact instead of blank restart.
  - Completed: 2026-05-29
  - Notes: On idle-expiry, `handle_resume` now builds a compacted prompt from the prior thread (via `build_compacted_session_prompt`) before clearing it, then auto-starts a fresh session seeded with that summary plus the user's prompt — instead of discarding context. User message reworded to "compacting prior context into a new session". Log events renamed to `session.expired.auto_compact` / `enqueue.resume_auto_compact`. Updated the two expired-session integration tests to assert the compacted prompt and compaction message.

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
