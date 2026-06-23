# TASK-0114: Prevent output delivery, chunking, and steering-side failures from aborting active agent runs

## Status
Immediate TODO.

## Context
On 2026-06-23, the `pycodebridge` channel session for repo `pycodebridge` showed an apparent Claude failure while the run was still active and heartbeat/steering behavior was in play.

Evidence examined:
- Bridge state: `/workspace/state/state.json`
- Unified session log: `/workspace/state/logs/session_jsonl/active/1474715794461032580/repo-pycodebridge__session-default.jsonl`
- Audit artifacts: `/workspace/state/logs/1474715794461032580/repo-pycodebridge__session-default/thread-pending/000155.*`
- Claude transcript: `/workspace/home/.claude/projects/-workspace-code-root-pycodebridge-wt-1474715794461032580-default/0f0471ad-cb05-486d-a9b0-f6560e7f8ba3.jsonl`
- Bridge log: `/workspace/state/logs/bridge.log`

The run at `2026-06-23T19:37:23Z` completed useful work:
- added worktree symlink support for `.venv` and `node_modules`
- ran tests successfully
- committed and pushed `50f1fde`
- emitted a final success message at `2026-06-23T19:42:46Z`

The bridge then recorded:

```json
{"event": "codex.exit", "data": {"error": "Separator is not found, and chunk exceed the limit"}}
```

That is not an agent process failure. It is an output delivery/chunking failure being surfaced through the agent runner callback path as an exit error. The timing also overlapped with user activity:
- `2026-06-23T19:38:58Z` — `!c done --merge` routed as a command while Claude was running
- `2026-06-23T19:39:49Z` and `2026-06-23T19:39:58Z` — messages routed through `relay.steer`
- `2026-06-23T19:42:47Z` — bridge logged the output chunking error as `codex.exit`

`!c done --merge` likely did not kill Claude directly: the `done` handler catches `TaskCloseError` when no task branch exists. The remaining risk is that send/chunk failures, and possibly steering reply failures, can unwind through active run callbacks and be misclassified as agent failures.

## Goal
Make output delivery and steering-side transport failures non-fatal to active agent subprocesses, and make logs distinguish transport/relay failures from real backend exits.

## Scope
- Ensure `_relay_output_text` never raises because `sink.send` fails.
- Add session JSONL events for output delivery failures, separate from `codex.exit`.
- Audit other active-run user interaction paths (`steer`, `answer`, `approve`, `deny`, `done`) for exceptions that can disrupt a running backend or produce misleading lifecycle logs.
- If `!c done` is sent while a session is active, return a clear operator message rather than trying to close the task branch mid-run.
- Ensure heartbeat stops only when the run relay is terminal or cleared, not because a transport send failed.

## Acceptance Criteria
- A sink/chunking failure during streamed output does not abort the run or get logged as `codex.exit`.
- The failure is logged as a transport/output event (`discord.output_failed` or equivalent) with error details and chunk length.
- Steering a running session cannot crash or misclassify the active run if the transport send path fails.
- `!c done --merge` during an active session is rejected or deferred with an explicit message.
- Targeted tests cover output send failure and at least one active-run command/steering conflict path.

## Recommended Agent Settings
- Model: `gpt-5.3-codex` or newer Codex model.
- Reasoning: `high`, because this touches run lifecycle, async callbacks, transport behavior, and operator-visible error classification.
