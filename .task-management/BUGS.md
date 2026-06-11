# BUGS

Rules:
- Bugs are tracked as tasks and must use stable IDs in format `TASK-####`.
- IDs are immutable, globally unique across `.task-management/`, and never reused.
- When a bug is scheduled for immediate work, move it to `.task-management/TODO.md` and keep the same ID.
- When a bug is deferred as general work, move it to `.task-management/BACKLOG.md` and keep the same ID.
- When a bug is fixed, remove it from this file and append it to `.task-management/DONE.md`.
- When a bug report is invalid/obsolete, remove it from this file and append it to `.task-management/REMOVED.md` with reason.

## Bug backlog

### TASK-0089: Successful agent runs can finish with no user-visible terminal message

**Symptom:** A Codex run can appear to think or make progress but never send a final answer. The next prompt can work normally, which suggests the prior run completed rather than remaining active.

**Root cause:** `run_codex` sends a success completion summary only through `_send_run_completion_summary` (`router.py:2164-2181`), and `_send_run_completion_summary` returns early when elapsed time is below `run_completion_min_seconds` (`router.py:2359-2371`). If the run exits 0 with no relayed assistant text, or with only parse-ignored JSON events such as reasoning/tool/final-result events, the bridge can clear active state and emit no user-facing completion or no-output notice. `on_jsonl` also ignores recognized events with no `texts` after usage/activity updates (`router.py:2660-2685`), so a terminal `result` event with no assistant text does not itself produce a response.

**Fix sketch:** Always emit a concise terminal notice when a successful run relayed zero assistant output, regardless of `run_completion_min_seconds`, for example "Run completed with no assistant message; use `!c logs` for details." Also audit recent Codex JSONL samples for final-answer schema changes and extend `CodexBackend.parse()` if final answer text now arrives under a different item/content type.

**Affected files:** `codebridge/routing/router.py`, `codebridge/codex.py`, `tests/test_integration_harness.py`

### TASK-0088: Final stream result does not stop heartbeat when the CLI process lingers

**Symptom:** Claude can appear to keep running and keep sending "working" heartbeat messages even though the agent session has logically ended.

**Root cause:** Backend parsers expose terminal stream events as `NormalizedEvent(type="result", ...)`, but the router does not treat `result` as a lifecycle signal. The run remains active and heartbeat continues until `proc.wait()` returns (`router.py:2106-2128`, `router.py:2332-2357`). The shared runner also invokes `on_exit` only after both stream readers finish and then `proc.wait()` returns (`agents/base.py:235-246`). If a CLI emits a final result but leaves the process or one stream open, the bridge has no grace-period watchdog to mark the run terminal, stop heartbeat, notify the user, or clean up the stuck process.

**Fix sketch:** Track terminal `result` events in `on_jsonl`, mark the run as terminal after a short grace period if the process has not exited, stop heartbeat once a final result is seen, and either kill/interrupt the lingering process or surface an explicit "agent emitted final result but process did not exit" error. Add Claude-focused coverage where a `result` event is emitted and `Process.wait()` never completes.

**Affected files:** `codebridge/routing/router.py`, `codebridge/agents/base.py`, `codebridge/agents/claude.py`, `tests/test_integration_harness.py`

### TASK-0086: Thread messages silently dropped when parent channel not in Discord cache

**Symptom:** Bot does not respond to messages sent in a Discord thread after bot restart or in large guilds, with no error sent to the user.

**Root cause:** `discord_parent_context` (`event_context.py:26-43`) always reads `parent_id` from `channel.parent_id` (always available on a Discord Thread), but only populates `parent_name` when `channel.parent` (the full channel object) is in Discord's local cache. When `parent` is not cached, `channel_name` falls back to the thread's own name (e.g., `"task-123"`). In `handle_message` (router.py:349-352), the channel regex (e.g., `codex-(.+)`) is matched against `event.channel_name`, which is now the thread's name rather than the parent channel's name — no match, message is silently dropped.

**Fix sketch:** In `normalize_event_context`, when `parent_name` is empty, derive the channel name from the parent channel ID by looking it up on the raw Discord message object (e.g., `getattr(message.guild, 'get_channel', None)` with `parent_id`), or fall back to formatting it as `codex-<parent_id>` so the regex at least has a chance. Alternatively, skip the channel-name regex check entirely when `event.platform_thread_id` is set and `parent_id` is known — the composite `channel_id` is always correct, so repo_name can be derived from a direct channel lookup rather than a name regex match.

**Affected files:** `codebridge/routing/event_context.py`, `codebridge/routing/router.py`
