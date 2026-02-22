# TODO (Public)

Current status:

TODO (Near-term):

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

Backlog:

- Role-based permissions model (Discord-role driven access tiers).
- Per-channel policy configuration (command/model/runtime policy by channel).
- Knowledge shortcuts/macros for repeatable repo workflows.
- Web-based/dashboard features (status/admin web surface, browser ops views).
