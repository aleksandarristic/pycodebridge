# TODO (Immediate)

Rules:
- Use stable task IDs in format `TASK-####`.
- IDs are immutable and never reused.
- Tasks promoted from `.task-management/BUGS.md` keep the same ID.
- When moving a task to backlog, keep the same ID.
- When completing a task, remove it from this file and append it to `.task-management/DONE.md`.
- When dropping a task, remove it from this file and append it to `.task-management/REMOVED.md`.

## Active tasks

- [TASK-0064] Single-parse the Codex JSONL stream path.
  - Context: each output line is currently JSON-parsed up to 3x and ANSI-stripped 3-4x. In `codebridge/codex.py` `_read_stdout` (~line 290) calls `extract_thread_id()` (json.loads) + `parse_event()` (json.loads) and strips text to feed `on_output`/`_capture_output` (which strips again in `router.py` ~1892); the `on_jsonl` callback then re-runs `parse_event()` (`router.py` ~2221), `display_texts()`, and `strip_control_codes()` (~2248), and `_relay_output_text` strips once more (~2367).
  - Goal: parse each line once and reuse the result; eliminate the duplicate work without changing observable behavior.
  - Scope:
    - Parse the line once in `codex.py` and pass the parsed `Event` (and/or raw payload) through the `on_jsonl` callback instead of re-parsing in the router.
    - Fold `last_output`/`output_events` tracking (currently in `_capture_output`) into the `on_jsonl` path so the redundant `on_output` processing can be dropped.
    - Collapse repeated `strip_control_codes()`/`display_texts()`/`needs_user_input()` passes to a single pass per line.
  - Acceptance criteria:
    - Behavior-preserving: relayed text, thread-id capture, awaiting-input detection, usage accounting, and audit/session-jsonl logging are unchanged.
    - Each output line is JSON-parsed at most once and stripped at most once before relay.
    - Existing `tests/test_codex.py`, `tests/test_router_*`, and integration-harness tests pass; add a test asserting single-parse (e.g. spy/counter on `json.loads` or `parse_event`).

- [TASK-0065] Coalesce Codex output relay into batched Discord sends.
  - Context: `router._relay_output_text` (`router.py` ~2358) sends one Discord message per output event/chunk, and `DiscordResponseSink.send` (`adapters/discord.py:114`) is a direct per-call network round-trip. Chatty runs emit many small `agent_message` events -> a burst of tiny messages that hits Discord's ~5 msg/s channel rate limit and stalls/spams the channel.
  - Goal: buffer streamed output and flush in fewer, larger messages to cut latency and rate-limit stalls.
  - Scope:
    - Buffer relayed output per (channel, session) and flush on a short time window and/or size threshold (default near `max_discord_message_chars`), with an immediate flush on run completion, awaiting-input ("Codex asks:"), and terminal/error events so nothing is lost or delayed past the run.
    - Make the flush window/size configurable with conservative defaults; preserve chunking at `max_discord_message_chars`.
    - Keep audit/session-jsonl output logging accurate relative to what is actually sent.
  - Acceptance criteria:
    - A run emitting many small events produces materially fewer `sink.send` calls while preserving content and ordering.
    - Awaiting-input prompts and final/key-result output are not delayed past their run.
    - Targeted tests cover buffering, threshold/window flush, and forced flush on terminal/awaiting-input events.
  - Note: the flush window is a UX/latency tunable (live-but-spammy vs batched-but-slightly-delayed); ship a conservative default, no blocking product decision.

- [TASK-0066] Track cached input tokens and verify/fix per-event usage summation.
  - Context: `usage_from_event` (`routing/helpers.py:113`) reads only `input_tokens`/`output_tokens`/`total_tokens` and discards `cached_input_tokens`. `update_usage` (`router.py:3272`) **sums** usage from every JSONL event; if Codex reports cumulative running totals within a single `exec` run, session/budget totals are over-counted.
  - Goal: account for cached tokens and ensure run/session usage is counted correctly (incremental, not double-counted).
  - Scope:
    - Confirm the real `codex exec --json` usage event shape (incremental vs cumulative; field names for cached tokens) against live output, and record the finding in the ticket/commit.
    - Capture `cached_input_tokens` (and `cachedInputTokens`) in `UsageStats`; surface it in `!c stats` and the run-completion summary.
    - If usage is cumulative, fix `update_usage` to store the latest totals (or compute deltas) instead of summing.
  - Acceptance criteria:
    - Usage totals match Codex's reported totals for a multi-event run (no over-count).
    - Cached tokens are tracked and visible in stats/summary output.
    - Tests cover the corrected accounting and cached-token parsing; existing usage/budget tests pass.
  - Depends-on for policy: see [TASK-0068] for whether budgets discount cached tokens.
