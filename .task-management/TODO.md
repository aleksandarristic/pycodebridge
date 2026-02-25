# TODO (Immediate)

Rules:
- Use stable task IDs in format `TASK-####`.
- IDs are immutable and never reused.
- Tasks promoted from `.task-management/BUGS.md` keep the same ID.
- When moving a task to backlog, keep the same ID.
- When completing a task, remove it from this file and append it to `.task-management/DONE.md`.
- When dropping a task, remove it from this file and append it to `.task-management/REMOVED.md`.

## Active tasks

- [TASK-0021] Remove dead command/DM helper code paths that no longer participate in runtime behavior.
  - Goal:
    - Reduce maintenance overhead by deleting clearly unused helpers/constants discovered during complexity review.
  - Details (human-readable):
    - This change removes old helper code that looks active but is never called in current routing/help flows.
    - Removing these stale paths reduces ambiguity for maintainers, shortens review surface, and lowers the chance of people updating the wrong function when changing command help/parsing behavior.
  - Scope:
    - Remove unused `AUTH_LABELS`, `_group_specs`, and `_ordered_groups` from `codebridge/commands/registry.py` if confirmed unused after final grep pass.
    - Remove unused `dm_help_text()` from `codebridge/handlers/dm_admin.py` if no external/runtime references exist.
    - Keep behavior unchanged; this is a no-feature, no-UX cleanup.
  - Acceptance criteria:
    - No command routing/help behavior changes in targeted tests.
    - No references remain to removed symbols.
    - Changed-area tests pass.

- [TASK-0022] Consolidate shortcut command parsing so DM and repo-channel paths share one canonical parser core.
  - Goal:
    - Eliminate duplicated shortcut parsing branches and alias drift between router and DM admin handlers.
  - Details (human-readable):
    - Today there are multiple places translating top-level `!<command>` and shorthand forms, which means alias fixes or new shortcuts must be patched in more than one file.
    - A shared parser core will make command behavior more predictable, reduce branching, and prevent “works in channel but not DM” inconsistencies.
  - Scope:
    - Introduce a shared shortcut normalization module/function (for example under `codebridge/commands/`).
    - Refactor `Router._shortcut_cmdline` and DM shortcut handling (`_dm_shortcut_cmdline` / `_prepare_dm_content`) to reuse shared logic.
    - Keep DM-only commands as an explicit extension layer rather than copy/pasting full mapping tables.
    - Add targeted tests for alias parity and shorthand behavior.
  - Acceptance criteria:
    - Shared shortcuts resolve identically in channel and DM flows where semantics should match.
    - DM-only shortcuts still work and remain explicitly scoped.
    - Targeted parser/routing tests pass with no regression in existing aliases.

- [TASK-0023] Centralize command authorization policy so `CommandSpec.auth` is the default source of truth.
  - Goal:
    - Reduce policy complexity and drift by aligning command metadata and enforcement logic.
  - Details (human-readable):
    - Command auth intent is currently declared in registry metadata but enforced through separate hardcoded router branches.
    - This task introduces a policy resolver that reads command spec auth first, then applies explicit overrides only for true subcommand-dependent rules.
    - Outcome is simpler auditing and safer future command additions because auth behavior is declared once and interpreted consistently.
  - Scope:
    - Implement a small auth-policy resolver used by both main router and DM prefixed command dispatch.
    - Keep explicit override handling for subcommand-sensitive cases (for example: `options show/set`, `lock status/extend`, `unlock status`, `git` high-risk remotes, `gh` unlock scope).
    - Update command tests to validate policy outcomes across open/unlock/totp/mixed modes.
  - Acceptance criteria:
    - New commands with `CommandSpec.auth` get correct default enforcement without additional router branching.
    - Existing special-case command behaviors remain intact and covered by targeted tests.
    - Auth regressions are guarded by explicit matrix-style test coverage.

- [TASK-0024] Refactor `Router.handle_message` into focused phases to reduce nested branching and mixed responsibilities.
  - Goal:
    - Improve readability and change safety in the highest-complexity router entrypoint.
  - Details (human-readable):
    - `handle_message` currently mixes prechecks, upload paths, plain-prompt relay behavior, command parsing, TOTP enforcement, and fallback routing in one long function.
    - Splitting it into phase-oriented helpers will make behavior easier to trace, reduce accidental coupling, and speed up debugging/review for future work.
  - Scope:
    - Extract helper methods for:
      - transport/guild/user prechecks
      - upload + pending-upload handling
      - unprefixed/plain prompt routing
      - prefixed command parsing/dispatch
    - Preserve current behavior and state transitions.
    - Add/adjust targeted tests where extraction changes call boundaries.
  - Acceptance criteria:
    - Functional behavior remains equivalent to current routing semantics.
    - `handle_message` orchestration becomes materially shorter and easier to inspect.
    - Changed-area routing tests pass.
