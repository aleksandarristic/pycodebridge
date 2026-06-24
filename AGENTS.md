# AGENTS

## Intent
- Maintain and evolve the Codex CLI Bridge (`pycodebridge`), a Python service that routes Discord messages to Codex CLI sessions mapped to local git repos.
- Keep changes safe for long-running bot behavior: favor explicit command handling, predictable state transitions, and transport-agnostic router behavior.
- Preserve existing architecture boundaries (`router` + handlers + adapters + services) unless a task explicitly calls for refactoring.

## Key behaviors
- Prefer small, reviewable patches with focused scope.
- Add or update tests whenever behavior changes.
- Keep command UX consistent with existing aliases/help text and auth expectations.
- Avoid introducing new dependencies unless necessary for the task.

## Python environment rule
- Always run Python-related commands inside the repo virtual environment.
- Use `./.venv/bin/...` for Python tooling, including:
  - `./.venv/bin/python`
  - `./.venv/bin/pip`
  - `./.venv/bin/pytest`
- Do not use system `python`, `pip`, or `pytest` for repo tasks.

## Local runtime environment
- Do not assume every agent run has the same surrounding tooling. At the start
  of any task that needs build, preview, or external CLI verification, check the
  current session for the required commands before deciding which verification
  steps are available.
- If present, `.agent-env.local.md` is a gitignored environment note for quick
  orientation. Treat it as a cache only; verify relevant commands before relying
  on it.

## Baseline workflow
- Validate quickly before/after non-trivial edits:
  - Run only tests related to changed code.
- During iteration and final validation, prefer targeted test modules/cases over full-suite runs.
- If a command cannot be run (missing config, credentials, external service), report the blocker clearly.

## Common commands
- Run tests (targeted): `./.venv/bin/pytest -q tests/<relevant_test_module>.py`
- Run bridge directly: `./.venv/bin/python -m cmd.bridge -config config.yaml`
- Optional preflight wrapper: `./run.sh --check`

## Task management
- Task files live in `.task-management/`:
  - `.task-management/TODO.md` for immediate work only.
  - `.task-management/BACKLOG.md` for deferred work.
  - `.task-management/BUGS.md` for bug backlog items.
  - `.task-management/DONE.md` for completed tasks.
  - `.task-management/REMOVED.md` for dropped/cancelled tasks.
- Task ID scope is global across all task management files above; IDs are stable and never reused.
- Every task must have a stable ID in format `TASK-####`.
- IDs persist when tasks move between TODO/BACKLOG/BUGS/DONE/REMOVED.
- Use `.task-management/TASK_COUNTER.md` as the source of truth for task ID allocation.
  - The counter stores the last assigned task ID only.
  - Next task ID is computed by incrementing the counter by one.
  - Whenever a new task is created in any task file, update the counter in the same change.
- Completed tasks are removed from TODO, BACKLOG, or BUGS and appended to DONE.
- Removed tasks are removed from TODO, BACKLOG, or BUGS and appended to REMOVED with reason.

## Done criteria
- Behavior change is implemented and covered by tests (or explicit reason given if coverage is not possible).
- Relevant/changed-area tests pass locally (full suite not required by default).
- User-visible command/output changes are reflected in docs when applicable.

## Operator preferences (persisted)
- Keep responses concise; avoid unnecessary verbosity.
- Do not run the full test suite by default; run only tests related to changed code.
- For new features, include a brief recommendation for model and reasoning settings appropriate to task complexity.

## Notes
- Supported transport: Discord.
