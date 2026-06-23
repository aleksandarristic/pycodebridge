# TASK-0096 — SessionState.worktree_path field + persistence

**Branch:** `feature/worktree-session-isolation`
**Depends on:** TASK-0094, TASK-0095
**Status:** TODO

## Goal

Extend `SessionState` with a `worktree_path` field so the bridge can remember which
worktree directory is active for a session, survive a process restart with the path
intact, and clean up orphaned worktrees on next startup.

---

## Changes

### `codebridge/sessions/state.py`

**`SessionState` dataclass** — add one field at the end:

```python
worktree_path: str = ""
```

Full updated dataclass:
```python
@dataclass
class SessionState:
    repo_name: str
    repo_path: str
    thread_id: str
    model: str = ""
    reasoning_effort: str = ""
    backend: str = ""
    worktree_path: str = ""   # ← new
    created_at: str = ""
    last_used_at: str = ""
```

**`_from_dict`** — in the `SessionState(...)` constructor call inside the loop, add:
```python
worktree_path=s.get("worktree_path", ""),
```

**`_to_dict`** — in the `sessions[name] = {...}` dict, add:
```python
"worktree_path": s.worktree_path,
```

**`_migrate_legacy`** — no change needed (new field defaults to `""`).

---

## Tests

Extend `tests/test_sessions_state.py` (or whichever file covers `Store` / `FileState`
round-trips) with:

| Test | What it checks |
|---|---|
| `test_worktree_path_round_trips` | Save state with `worktree_path="/tmp/foo"`, reload, value survives |
| `test_worktree_path_defaults_empty` | Old state JSON without `worktree_path` key deserializes to `""` |
| `test_worktree_path_cleared` | Setting `worktree_path=""` serializes as `""` (not absent) |

---

## Done criteria

- `SessionState` has `worktree_path`
- JSON round-trip preserves the value
- Missing key in old JSON files deserializes gracefully to `""`
- No existing state tests broken
