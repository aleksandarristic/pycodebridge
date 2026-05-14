# TODO (Immediate)

Rules:
- Use stable task IDs in format `TASK-####`.
- IDs are immutable and never reused.
- Tasks promoted from `.task-management/BUGS.md` keep the same ID.
- When moving a task to backlog, keep the same ID.
- When completing a task, remove it from this file and append it to `.task-management/DONE.md`.
- When dropping a task, remove it from this file and append it to `.task-management/REMOVED.md`.

## Active tasks

- [TASK-0036] Fix missing `import re` in `audit.py` — `Redactor` crashes at runtime.
  - `codebridge/observability/audit.py:200` calls `re.compile()` but `re` is never imported.
  - Breaks all `test_audit_redaction` tests; if `audit.redact: true` is set, the bridge crashes at startup.
  - Fix: add `import re` to the imports in `audit.py`.

- [TASK-0037] Deduplicate bool-parsing logic in `state.py`.
  - `sessions/state.py` defines its own `_BOOL_TRUE`/`_BOOL_FALSE` sets and `_normalize_bool()`, duplicating the equivalent logic already in `util/coerce.py:parse_bool`.
  - Fix: remove the duplicate sets and rewrite `_normalize_bool` to call `parse_bool`, catching `ValueError` and returning `None`.

- [TASK-0038] Remove dead validation branch in `_validate_repo_name`.
  - `util/path.py:59` — the `any(c in repo_name for c in ("/", "\\", ":")) or repo_name == ".."` check is unreachable; the regex `^[A-Za-z0-9._-]+$` already excludes all those characters.
  - Fix: remove the second condition (or add a comment if kept as explicit defence-in-depth).

- [TASK-0039] Replace `assert` statements in production code with proper guards.
  - Three `assert` calls that are silently dropped under `python -O`:
    - `codebridge/codex.py:289` — `assert proc.stdout` in hot async reader path.
    - `codebridge/routing/router.py:1158` — `assert ttl_seconds is not None` after `_parse_lock_action`.
    - `codebridge/routing/router.py:1491` — `assert isinstance(queued_ids, list)` in reset-all handler.
  - Fix: replace each with an `if`-guard that raises `RuntimeError` or handles the case gracefully.

- [TASK-0040] Remove redundant `.git` filter in `_suggest_upload_paths`.
  - `services/file_transfer.py:187` — `.git` is already excluded by the `name.startswith(".")` check on the line above; the `{".git", "node_modules", "vendor"}` set check for `.git` is dead code.
  - Fix: remove `.git` from the set (keep `node_modules` and `vendor`).

- [TASK-0041] Clarify or remove misleading double `_purge_session_artifacts` call.
  - `routing/router.py:1582-1585` — `_purge_session_artifacts` is called twice with a `asyncio.sleep(0)` between each call; the second call always returns 0 because artifacts were already deleted, making the `+= 0` misleading.
  - Fix: either document the intent with a comment (if the double yield is needed for exit callbacks) or remove the second call.
