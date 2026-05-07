# Command Model Redesign (TASK-0034)

This document defines the minimal operator-facing command model that should drive help text, docs, and future deprecation work.

It does not remove working commands yet. The goal is to make the preferred workflow explicit and keep legacy/admin commands available without giving them equal prominence.

## Design goals

- Keep the normal channel workflow small enough to memorize.
- Prefer explicit `!c ...` commands for most actions.
- Reserve top-level shorthand for high-frequency active-run interaction only.
- Keep `git` and `gh` as escape hatches instead of growing many narrow wrappers.
- Separate admin/setup/diagnostic controls from the daily repo workflow.

## Minimal core workflow

These are the first-class commands that should lead docs and help:

- Orientation: `help`, `status`
- Session lifecycle: `start`, `resume`, `use`, `reset`
- Active-run control: `answer`, `approve`, `deny`, `steer`, `stop`, `wait`
- Repo inspection: `show`, `changes`, `tests`, `branch`
- Escape hatches: `git`, `gh`

Core shorthand that stays promoted:

- `!a <text>` and `!a:<session> <text>` for `answer`
- `!s <text>` and `!s:<session> <text>` for `steer`
- `!y` for `approve`
- `!n` for `deny`

Top-level shortcuts that remain supported but should not be prominent in docs:

- Generic `!<command>` forms such as `!status`, `!branch`, `!git`
- Compatibility aliases such as `!reset`, `!pause`, `!diag`, `!u`

## Support and advanced workflow

These commands still matter, but they should appear after the golden path:

- Session support: `choose`
- Run support: `interrupt`, `/quit`, `cancel`
- Diagnostics support: `ps`
- Advanced session/repo tools: `model`, `models`, `spec`, `download`, `rerun`, `peek`, `updates`, `health`

## Admin and setup surface

These commands should be grouped under admin/diagnostic help, not mixed into the main workflow:

- Security and runtime config: `unlock`, `lock`, `options`, `config`
- Session maintenance: `thread`, `purge`, `session`
- Repo lifecycle: `create`, `clone`, `copy`
- Destructive run/admin controls: `kill`
- Diagnostics/audit: `stats`, `budget`, `logs`, `audit`

DM admin commands should follow the same rule:

- lead with repo binding and run controls
- place repo lifecycle, reset-all, config, and cross-channel inventory under admin-only sections

## Overlap decisions

- `status` is the primary orientation command.
- `stats`, `peek`, `ps`, `logs`, and `audit` are diagnostic follow-ons, not peers to `status`.
- `reset` is the primary operator reset verb.
- `purge` and `session ...` remain available for maintenance, not as part of the main loop.
- `stop` is the primary run interruption verb for channel usage.
- `interrupt`, `/quit`, and `kill` stay available as lower-level controls.
- `show`, `changes`, `tests`, and `branch` stay as convenience wrappers because they cover common repo questions quickly.
- `git` and `gh` remain the explicit escape hatches when wrappers are insufficient.

## Channel vs DM structure

- Channel help should present the repo workflow first, then advanced/support commands, then admin/diagnostics.
- DM help should present repo binding and run interaction first.
- DM admin-only commands should be clearly separated from standard DM operator commands.

## Migration guidance

- Keep existing aliases working during the transition.
- Stop promoting broad top-level `!<command>` forms in docs/help, except for the active-run shorthand listed above.
- Prefer canonical examples in docs:
  - `!c start`
  - `!c resume`
  - `!c reset`
  - `!c show`
  - `!c git ...`
- Treat old aliases as compatibility surface, not the recommended interface.

## Code mapping

The current source-of-truth metadata for this redesign lives in `codebridge/commands/registry.py` via `COMMAND_MODEL_META`, `command_surface(...)`, and `command_namespace(...)`.
