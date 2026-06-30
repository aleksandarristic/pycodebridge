# BUGS

Rules:
- Bugs are tracked as tasks and must use stable IDs in format `TASK-####`.
- IDs are immutable, globally unique across `.task-management/`, and never reused.
- When a bug is scheduled for immediate work, move it to `.task-management/TODO.md` and keep the same ID.
- When a bug is deferred as general work, move it to `.task-management/BACKLOG.md` and keep the same ID.
- When a bug is fixed, remove it from this file and append it to `.task-management/DONE.md`.
- When a bug report is invalid/obsolete, remove it from this file and append it to `.task-management/REMOVED.md` with reason.

## Bug backlog

- [TASK-0132] Long-running Discord session can stay in "working for ..." state without meaningful output and without enough evidence to explain why.
  - Context: A pycodebridge session in this repo was observed from Discord staying in the heartbeat state (`Codex working for ...`) for roughly 22 minutes on a seemingly trivial task, with no useful streamed output to explain whether the agent was legitimately busy, waiting on hidden input/approval, hung in a subprocess/tool call, or left behind in stale bridge state.
  - Impact:
    - Operators cannot quickly tell whether they should wait, steer, interrupt, kill, reset, or restart the bridge.
    - Existing diagnostics are fragmented: `!c status`, `!c peek`, `!c logs`, bridge logs, per-request audit logs, and session JSONL logs exist, but the bridge does not provide one reliable workflow to answer "what is this run currently doing?".
    - In the local repo config, `state.log_dir` is `/Users/leka/Code/_bridge/logs`, but the currently available artifacts there are stale (latest found: 2026-02-13), which also raises the possibility that the active Discord bot is running with different config/state paths than the checked-in `config.yaml`.
  - Goal:
    - Make this failure mode recoverable and explainable.
    - Ensure operators can determine whether a run is blocked on user input, idle with no output, orphaned, or actively producing hidden tool/subprocess work.
    - Ensure the active bridge instance/config can be identified from the running process and from Discord-visible diagnostics.
  - Scope:
    - Reproduce or capture a real stuck run and preserve its artifacts before reset/purge.
    - Audit the run-control and observability path around `_run_heartbeat`, `_run_watchdog`, `handle_peek`, `handle_logs`, audit artifacts, and session JSONL logging.
    - Confirm whether the active bot process writes to the configured `state.log_dir`, and whether unified `session_jsonl/active/...` logs are present for real runs.
    - Decide whether the fix is missing instrumentation, stale-state cleanup, missing idle detection surfacing, hidden approval/input prompts, or a backend subprocess hang.
    - Add any missing operator-facing diagnostics needed to answer:
      - Which config file/state dir/log dir is this run using?
      - What was the last agent JSONL event and when was it seen?
      - Is the run awaiting input/approval?
      - Is the tracked process still alive?
      - Has the watchdog already detected idle/orphan conditions?
  - Acceptance criteria:
    - A future occurrence can be triaged from logs and built-in commands without guesswork.
    - Recovery guidance is documented and maps cleanly to actual run states.
    - Tests cover any new diagnostic or recovery behavior added for this bug.
