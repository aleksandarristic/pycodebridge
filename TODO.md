# TODO (Public)

TODO (Near-term):
- Discord threads as isolated session contexts (immediate).
  - Goal: allow each Discord thread under `#codex-<repo>` to act as an independent session workspace with first-class Discord UI.
  - Scope:
    - Resolve repo from parent mapped channel when message originates in a thread.
    - Treat each thread as an isolated room key (`discord:<channel_id>:<thread_id>`).
    - Keep session namespace, queue, sticky selection, and run control isolated per thread room.
    - Preserve existing behavior for non-thread channel messages.
  - Acceptance criteria:
    - `!c start` in parent channel and in multiple threads can run concurrently for the same repo.
    - Output and follow-up commands stay scoped to the originating thread.
    - Commands in one thread do not affect sessions in sibling threads.
    - Existing channel-only workflows remain backward compatible.
    - Add targeted integration tests covering thread isolation and parent-channel compatibility.

Backlog:

- Final-message ordering hardening for run lifecycle output.
  - Goal: prevent stale/intermediate progress updates from appearing after a run-complete message.
  - Scope:
    - Emit a single authoritative terminal event for each run (success/failure/cancelled).
    - Suppress or ignore late progress events once terminal state is set.
    - Add clear run-state metadata so transports can order/filter consistently.
  - Acceptance criteria:
    - After terminal event emission, no additional progress update is delivered for that run.
    - User-visible last message is always terminal status for the run.
    - Regression test covers out-of-order event delivery scenario.

- Compose + global skill defaults for cross-repo persistence (deferred).
  - Goal: define and document a non-`AGENTS.md` channel for durable operator defaults across repos/sessions.
  - Approach:
    - Use user-level Codex skills persisted in mounted Codex home (`CODEX_AUTH_HOST -> /workspace/home/.codex` in Compose).
    - Optionally set `codex.env.CODEX_HOME=/workspace/home/.codex` in `config.docker.yaml` for explicit subprocess behavior.
  - Deliverables:
    - Add docs snippet with host-side skill path, minimal `SKILL.md` example, and Compose restart/apply steps.
    - Clarify precedence/coexistence with per-repo `AGENTS.md`.

- Role-based permissions model (Discord-role driven access tiers).
- Knowledge shortcuts/macros for repeatable repo workflows.
- Web-based/dashboard features (status/admin web surface, browser ops views).
