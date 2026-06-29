# pycodebridge — Agent Instructions

## Python environment

Always use the project venv — never system Python:
- `./venv/bin/python`, `./.venv/bin/pytest`, `./.venv/bin/pip`

## Testing

- Run only tests related to changed code: `./.venv/bin/pytest -q tests/<module>.py`
- Do not run the full suite by default.
- Tests live in `tests/` — one file per feature area.
- Done criteria: behavior change implemented + tests covering it + changed-area tests pass locally.

## Task management

- Task IDs: `TASK-####`, globally unique, never reused.
- Counter in `.task-management/TASK_COUNTER.md` — increment when creating tasks.
- Completed tasks: remove from TODO/BACKLOG/BUGS, append to DONE with completion date and notes.
- Dropped tasks: remove, append to REMOVED with reason.

## Commits

- One commit per task, self-contained: code + tests + task-management move in the same commit.
- Never add a `Co-Authored-By` trailer.
- Do not ask for confirmation before running tests or committing — run changed-area tests and commit when done.

## Branch and remote hygiene

In direct chat (including via Discord), never create worktrees or session/task branches — work directly on the current branch.

Worktrees are for local parallel agent work only, and only when explicitly requested.

- Never `git push` a worktree or session branch to remote. Worktree branches (prefixed `session/`, `task/`, or similar) are ephemeral and must stay local.
- Never push any branch to remote unless the user explicitly asks.
- Never open a PR unless the user explicitly asks.
- After parallel agent work is done and results are merged back to the working branch, the worktree branch should be deleted locally — do not let it accumulate.
