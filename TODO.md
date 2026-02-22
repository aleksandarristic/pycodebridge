# TODO (Public)

Current status:

TODO (Near-term):

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

- Router/module architecture reorganization (human-readable hierarchy).
  - Goal: redesign code layout so related router concerns are grouped into clear packages/modules with explicit boundaries.
  - Scope:
    - Consolidate router-related files into a coherent package tree (for example: routing/core, routing/auth, routing/commands, routing/runtime, routing/io).
    - Move command dispatch/alias/help parsing concerns into consistent command modules.
    - Separate transport-facing orchestration from domain/state/update logic to reduce cross-file coupling.
  - Quality bar:
    - Import graph becomes easier to follow (minimal circular risk, predictable dependency direction).
    - File/module names reflect responsibility; no ambiguous “helpers” catch-alls for core logic.
    - Public entrypoints remain stable (no user-facing command regressions).
  - Deliverables:
    - Proposed target package map and migration plan.
    - Incremental refactor PR sequence with tests green at each step.
    - Updated docs section describing architecture layout and ownership boundaries.

Backlog:

- Role-based permissions model (Discord-role driven access tiers).
- Per-channel policy configuration (command/model/runtime policy by channel).
- Knowledge shortcuts/macros for repeatable repo workflows.
- Web-based/dashboard features (status/admin web surface, browser ops views).
