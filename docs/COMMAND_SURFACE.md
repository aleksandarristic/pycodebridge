# Command Surface Inventory (TASK-0033)

This document inventories all operator-facing command entry points in `pycodebridge`.

## Preferred operator workflow (TASK-0035)

The inventory below is still the full compatibility surface, but the preferred help/docs order is now:

- Golden path: `help`, `status`, `start`, `resume`, `use`, `reset`, `answer`, `steer`, `approve`, `deny`, `stop`, `wait`, `show`, `changes`, `tests`, `branch`, `git`, `gh`
- Promoted run shortcuts only: `!a`, `!s`, `!y`, `!n`
- Support/advanced commands after the golden path: `choose`, `workflow`, `interrupt`, `/quit`, `cancel`, `ps`, `model`, `models`, `spec`, `download`, `rerun`, `peek`, `updates`, `health`
- Admin/maintenance commands last: security/runtime config, session maintenance, repo lifecycle, audit/log inspection

Docs and help should prefer canonical `!c ...` examples for most commands and treat generic top-level `!<command>` forms as compatibility surface rather than the main interface.

## Classification legend

- Audience: `Channel`, `DM`, or `DM admin`.
- Context: where the command is accepted.
- Auth mode: `open`, `unlock/default`, `unlock/gh`, `totp`, or `mixed`.
- Backend: dominant execution path (`bridge-local`, `codex`, `git`, `gh`, `audit/state`).
- Category: `essential`, `convenience`, `admin-only`, or `likely redundant`.

## Channel command registry (`!c ...`)

Source of truth: `codebridge/commands/registry.py`.

| Command | Aliases | Audience | Context | Auth | Backend | Category |
|---|---|---|---|---|---|---|
| `help [command]` | `commands` | Channel | repo channel/thread | open | bridge-local | essential |
| `status` | `st` | Channel | repo channel/thread | open | bridge-local | essential |
| `stats [session]` | `usage` | Channel | repo channel/thread | open | audit/state | likely redundant |
| `budget ...` | `budgets` | Channel | repo channel/thread | open | audit/state | admin-only |
| `peek [session]` | `pk` | Channel | repo channel/thread | open | state | likely redundant |
| `updates` | `update`, `version`, `u` | Channel | repo channel/thread | open | bridge-local | convenience |
| `health` | `diag` | Channel | repo channel/thread | open | bridge-local | convenience |
| `config` | `cfg` | Channel | repo channel/thread | unlock/default | bridge-local | admin-only |
| `options ...` | `opts` | Channel | repo channel/thread | mixed | state | admin-only |
| `unlock ...` | `ul` | Channel | repo channel/thread | totp | security state | essential |
| `lock ...` | `lk` | Channel | repo channel/thread | mixed | security state | essential |
| `start [session]` | `run` | Channel | repo channel/thread | unlock/default | codex | essential |
| `resume [session] <prompt>` | `rs` | Channel | repo channel/thread | unlock/default | codex | essential |
| `choose [session] continue\|new\|compact` | `pick` | Channel | repo channel/thread | unlock/default | state/codex | essential |
| `use <session>` | `select` | Channel | repo channel/thread | unlock/default | state | essential |
| `model [session] <id\|default> [reasoning\|default]` | `mdl` | Channel | repo channel/thread | unlock/default | state/codex config | convenience |
| `effort [session] <level\|default>` | `eff` | Channel | repo channel/thread | unlock/default | state/codex config | convenience |
| `models [session]` | `mdls` | Channel | repo channel/thread | open | codex/cache | convenience |
| `thread [session] <id>` | `tid` | Channel | repo channel/thread | unlock/default | state | admin-only |
| `reset [session]` | none | Channel | repo channel/thread | unlock/default | state | essential |
| `workflow [session] <inspect\|fix\|review\|ship> [focus]` | `wf` | Channel | repo channel/thread | unlock/default | codex | convenience |
| `purge [session] \| purge stale <ttl>` | none | Channel | repo channel/thread | unlock/default | state/filesystem | admin-only |
| `session ...` | `sess` | Channel | repo channel/thread | unlock/default | state/filesystem | admin-only |
| `spec [session]` | `plan` | Channel | repo channel/thread | unlock/default | codex | convenience |
| `create` | `createrepo`, `new` | Channel | repo channel/thread | totp | filesystem/git | admin-only |
| `clone <url>` | `clonerepo` | Channel | repo channel/thread | totp | git | admin-only |
| `copy <newname>` | `copyrepo`, `cp` | Channel | repo channel/thread | totp | filesystem/git | admin-only |
| `stop [session]` | `pause` | Channel | repo channel/thread | unlock/default | codex control | essential |
| `interrupt [session]` | `int`, `esc`, `escape` | Channel | repo channel/thread | unlock/default | codex control | convenience |
| `kill [session]` | none | Channel | repo channel/thread | unlock/default | codex control | admin-only |
| `/quit [session]` | none | Channel | repo channel/thread | unlock/default | codex control | convenience |
| `steer [session] -- <text>` | none | Channel | repo channel/thread | unlock/default | codex | essential |
| `answer [session] -- <text>` | `reply` | Channel | repo channel/thread | unlock/default | codex | essential |
| `approve [session]` | `y` | Channel | repo channel/thread | unlock/default | codex | convenience |
| `deny [session]` | `n` | Channel | repo channel/thread | unlock/default | codex | convenience |
| `wait` | `w` | Channel | repo channel/thread | unlock/default | state | essential |
| `show` | `showrepo`, `tree` | Channel | repo channel/thread | open | bridge-local | convenience |
| `changes` | `showchanges` | Channel | repo channel/thread | open | git | convenience |
| `tests` | `test` | Channel | repo channel/thread | unlock/default | pytest | convenience |
| `branch` | none | Channel | repo channel/thread | open | git | convenience |
| `git <...>` | none | Channel | repo channel/thread | unlock/default | git | essential |
| `gh <args>` | none | Channel | repo channel/thread | unlock/gh | gh | essential |
| `gh-create [--public]` | none | Channel | repo channel/thread | unlock/gh | gh/git | convenience |
| `download <path>` | `dl` | Channel | repo channel/thread | unlock/default when `discord.totp.command_groups.file_transfer` is enabled | filesystem | convenience |
| `logs [session] [n]` | `log` | Channel | repo channel/thread | unlock/default | audit | admin-only |
| `audit ...` | none | Channel | repo channel/thread | unlock/default | audit | admin-only |
| `ps` | none | Channel | repo channel/thread | open | queue state | essential |
| `cancel <job-id>` | `drop` | Channel | repo channel/thread | unlock/default | queue control | essential |
| `rerun` | `retry` | Channel | repo channel/thread | unlock/default | queue control | convenience |

## Attachment-triggered workflows

| Workflow | Trigger | Audience | Context | Auth | Backend | Category |
|---|---|---|---|---|---|---|
| Upload files | Attach one or more files, then reply with a repo-relative destination path | Channel/DM | repo channel/thread or bound DM | totp when `discord.totp.command_groups.file_transfer` is enabled | filesystem | convenience |

For one uploaded file, the destination reply can be a file path such as
`docs/input.txt`. For multiple uploaded files, the destination reply must be a
directory path such as `uploads/`.

## Channel top-level shortcuts (`!<command>`)

Source of truth: `codebridge/commands/shortcuts.py` and router shortcut normalization.

- Generic top-level forms for all registered command names and aliases: `!help`, `!status`, `!model`, `!git`, `!gh`, etc.
- Session-targeted shorthand:
- `!s <text>` -> `steer <text>`
- `!s:<session> <text>` -> `steer <session> -- <text>`
- `!a <text>` -> `answer <text>`
- `!a:<session> <text>` -> `answer <session> -- <text>`
- Conflict resolution shorthand:
- `!cont` or `!continue` -> `choose continue`
- `!new` -> `choose new`
- `!compact` or `!cpt` -> `choose compact`

## DM command surface

Source of truth: `codebridge/handlers/dm_admin.py`.

### Repo-bound/operator DM commands

| Command | Aliases | Audience | Context | Auth | Backend | Category |
|---|---|---|---|---|---|---|
| `help [command]` | `commands` | DM | owner DM | open | bridge-local | essential |
| `bind <repo>` | none | DM | owner DM | unlock/default | state | essential |
| `use <repo>` | none | DM | owner DM | unlock/default | state | convenience |
| `repo <repo> <prompt>` | none | DM | owner DM | unlock/default | codex | essential |
| `unbind` | none | DM | owner DM | unlock/default | state | convenience |
| `status` | `st` | DM | owner DM | open | state | essential |
| `answer [session] -- <text>` | `reply` | DM | owner DM | unlock/default | codex | essential |
| `approve [session]` | none | DM | owner DM | unlock/default | codex | convenience |
| `deny [session]` | none | DM | owner DM | unlock/default | codex | convenience |
| `gh <args>` | none | DM | owner DM | unlock/gh | gh | essential |
| `updates` | `u` | DM | owner DM | open | bridge-local | convenience |
| `health` | `diag` | DM | owner DM | open | bridge-local | convenience |
| `options ...` | `opts` | DM | owner DM | mixed | state | admin-only |
| `unlock ...` | `ul` | DM | owner DM | totp | security state | essential |
| `lock ...` | `lk` | DM | owner DM | mixed | security state | essential |

### DM admin-only commands

| Command | Aliases | Audience | Context | Auth | Backend | Category |
|---|---|---|---|---|---|---|
| `repos` | none | DM admin | owner DM | open | filesystem | admin-only |
| `sessions` | none | DM admin | owner DM | open | state | admin-only |
| `config` | none | DM admin | owner DM | unlock/default | bridge-local | admin-only |
| `reset all` | none | DM admin | owner DM | totp + confirmation | state/filesystem | admin-only |
| `create/new <name>` | `new` | DM admin | owner DM | totp | filesystem/git | admin-only |
| `clone <name> <url>` | none | DM admin | owner DM | totp | git | admin-only |
| `copy/cp <from> <to>` | `cp` | DM admin | owner DM | totp | filesystem/git | admin-only |
| `deleterepo/del <name>` | `del`, `delete` | DM admin | owner DM | totp + confirmation | filesystem | admin-only |
| `renamerepo/ren <from> <to>` | `ren`, `rename` | DM admin | owner DM | totp | filesystem/state | admin-only |

## Overlap summary

- Core workflow is present but mixed with diagnostics/admin commands in the same top-level namespace.
- Significant overlap exists among status-style commands (`status`, `stats`, `peek`, `ps`, `logs`, `audit`).
- Session lifecycle is fragmented across `start`, `resume`, `choose`, `use`, `reset`, `purge`, and `session`.
- Bridge wrappers overlap with raw passthrough commands (`show`/`changes`/`branch` vs `git`, and many GH admin paths vs `gh`).

This inventory is intended as the baseline for `TASK-0034` and `TASK-0035` redesign/deprecation work.
