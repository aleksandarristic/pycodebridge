# TODO (Public)

High-level items on the roadmap:

- Improve end-command usage reporting (quit/stop/kill).
- Make `!c status` reliably include a Codex status summary.
- Unify command parsing utilities.
- Formalize session lifecycle invariants.

Optimization tasks from code review:

- Replace direct `asyncio.Queue` internals access in `codebridge/queue.py`.
  - Remove usage of `_queue._queue` for snapshot/cancel.
  - Implement cancellation/snapshot using public, stable data structures/APIs.
  - Ensure queue accounting stays correct for cancelled jobs.

- Add worker lifecycle management in `codebridge/queue.py`.
  - Avoid keeping per-channel workers alive forever after channels go idle.
  - Add cleanup/pruning for idle workers and related in-memory worker state.

- Reduce repeated state file loads on hot command paths.
  - Avoid multiple `state.load()` calls within one command flow (`start`, `resume`, status-like paths).
  - Reuse a per-request state snapshot where practical to reduce lock/I/O churn.

- Optimize `!c status` data gathering.
  - Build status output from a single loaded state snapshot and a single active-process snapshot.
  - Avoid per-session repeated state lookups for model/reasoning display.
