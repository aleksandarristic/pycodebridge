# TODO (Public)

Current status:
- Completed: repository-wide module architecture reorganization into hierarchical packages
  (`routing/`, `commands/`, `sessions/`, `services/`) with backward-compatible top-level shims and updated docs.

TODO (Near-term):
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

Backlog:

- Multi-room sessions per repo (room mapping redesign, open question).
  - Goal: support multiple chat rooms working on the same repo concurrently, with one default room plus additional dedicated spin-off rooms.
  - Desired UX:
    - Keep a canonical/default room per repo.
    - Allow creating a new room for a new session on the same repo using a similar room name pattern.
    - Allow parallel workstreams in different rooms while targeting the same repo safely.
  - Open question:
    - How should room-to-repo/session mapping evolve (naming convention, metadata binding, lifecycle/cleanup, and conflict handling)?
  - Initial considerations:
    - Avoid collisions with existing `codex-<repo>` mapping.
    - Preserve auth/permissions and command behavior across default vs spin-off rooms.
    - Define how room creation/binding commands should work in Discord and Telegram.

- Compose + global skill defaults for cross-repo persistence (deferred).
  - Goal: define and document a non-`AGENTS.md` channel for durable operator defaults across repos/sessions.
  - Approach:
    - Use user-level Codex skills persisted in mounted Codex home (`CODEX_AUTH_HOST -> /workspace/home/.codex` in Compose).
    - Optionally set `codex.env.CODEX_HOME=/workspace/home/.codex` in `config.docker.yaml` for explicit subprocess behavior.
  - Deliverables:
    - Add docs snippet with host-side skill path, minimal `SKILL.md` example, and Compose restart/apply steps.
    - Clarify precedence/coexistence with per-repo `AGENTS.md`.

- Live steering reliability validation (operator-assisted test).
  - Goal: verify that `!s <text>` reliably reaches an active run and changes outcome.
  - Test setup:
    - Start a long-running task that naturally allows mid-run intervention (5+ minutes), for example:
      - “scan repo and produce an exhaustive architecture + risk report with per-file notes and remediation plan”.
    - Require the run to stream intermediate progress so we can time the steer.
  - Steering action (mid-run):
    - Send `!s Focus only on top 3 risks; stop broad inventory; produce concise prioritized fixes with exact file paths.`
    - Optional second steer to confirm repeatability:
      - `!s Do not add new scope. Finish now with only the prioritized fix plan.`
  - Verification checklist:
    - Bot acknowledges steer (`Sent steer input to session '...'`).
    - Subsequent output visibly pivots from broad inventory to the steered format/scope.
    - Final output reflects steer constraints (top 3 only, prioritized fixes, exact file refs, reduced scope).
    - No silent drop (if steer is malformed or empty, explicit usage/validation message appears).
  - Pass criteria:
    - At least 2 successful steer injections in one run, both acknowledged and reflected in output.
  - Fail criteria:
    - Missing steer acknowledgement, no output pivot after acknowledged steer, or unexplained no-op behavior.
  - Artifacts to capture:
    - Command transcript (`start` + steer messages), timestamps, and final output snippet showing scope change.

- Role-based permissions model (Discord-role driven access tiers).
- Per-channel policy configuration (command/model/runtime policy by channel).
- Knowledge shortcuts/macros for repeatable repo workflows.
- Web-based/dashboard features (status/admin web surface, browser ops views).
