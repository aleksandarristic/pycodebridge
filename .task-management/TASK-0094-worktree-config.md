# TASK-0094 — WorktreeConfig: dataclass + YAML loading + validation

**Branch:** `feature/worktree-session-isolation`
**Status:** TODO

## Goal

Add a `WorktreeConfig` dataclass to `codebridge/config.py` and wire it fully into the
config loading pipeline (apply, defaults, path expansion, validation).

This is the first task in the worktree session-isolation feature. No behaviour changes
yet — just config plumbing so subsequent tasks can read `cfg.worktrees.*`.

---

## Changes

### `codebridge/config.py`

**New constants (near top):**
```python
DEFAULT_WORKTREE_BASE_DIR = ""         # empty = sibling of repo dir
DEFAULT_WORKTREE_MAX_PER_REPO = 8
DEFAULT_WORKTREE_CLEANUP_ON_END = "remove"  # remove | keep | pr
```

**New dataclass (add after `RepoBootstrapConfig`):**
```python
@dataclass
class WorktreeConfig:
    """Git worktree isolation configuration."""
    enabled: bool = False
    base_dir: str = DEFAULT_WORKTREE_BASE_DIR
    max_per_repo: int = DEFAULT_WORKTREE_MAX_PER_REPO
    cleanup_on_end: str = DEFAULT_WORKTREE_CLEANUP_ON_END
```

**`Config` dataclass** — add field:
```python
worktrees: WorktreeConfig = field(default_factory=WorktreeConfig)
```

**`_apply_dict`** — add a block reading the `worktrees:` YAML section:
```python
worktrees = raw.get("worktrees", {}) or {}
cfg.worktrees.enabled = _coerce_bool(
    worktrees.get("enabled", cfg.worktrees.enabled),
    "worktrees.enabled",
)
cfg.worktrees.base_dir = str(worktrees.get("base_dir", cfg.worktrees.base_dir) or "")
cfg.worktrees.max_per_repo = int(worktrees.get("max_per_repo", cfg.worktrees.max_per_repo))
cfg.worktrees.cleanup_on_end = str(worktrees.get("cleanup_on_end", cfg.worktrees.cleanup_on_end) or DEFAULT_WORKTREE_CLEANUP_ON_END)
```

**`_apply_defaults`** — add:
```python
cfg.worktrees.enabled = _coerce_bool(cfg.worktrees.enabled, "worktrees.enabled")
if cfg.worktrees.max_per_repo <= 0:
    cfg.worktrees.max_per_repo = DEFAULT_WORKTREE_MAX_PER_REPO
if not cfg.worktrees.cleanup_on_end:
    cfg.worktrees.cleanup_on_end = DEFAULT_WORKTREE_CLEANUP_ON_END
```

**`_expand_paths`** — add:
```python
cfg.worktrees.base_dir = _expand_path(cfg.worktrees.base_dir)
```

**`_validate`** — add:
```python
cleanup = (cfg.worktrees.cleanup_on_end or "").strip().lower()
if cleanup not in {"remove", "keep", "pr"}:
    raise ValueError("worktrees.cleanup_on_end must be remove|keep|pr")
cfg.worktrees.cleanup_on_end = cleanup
if cfg.worktrees.max_per_repo < 1 or cfg.worktrees.max_per_repo > 64:
    raise ValueError("worktrees.max_per_repo must be between 1 and 64")
```

### `config.example.yaml`

Add a commented-out section (place it after the `repo_bootstrap:` section):

```yaml
# worktrees:
#   enabled: false          # set true to give each session its own git worktree
#   base_dir: ""            # empty = sibling directory of the repo (e.g. myrepo-wt-<id>/)
#   max_per_repo: 8         # refuse new sessions if this many worktrees exist for a repo
#   cleanup_on_end: remove  # remove | keep | pr
```

---

## Tests

**File:** `tests/test_config_worktrees.py`

Cover:
- Default values load correctly when `worktrees:` key is absent from YAML
- `enabled: true` round-trips correctly
- `base_dir` is path-expanded (`~` and `$VAR`)
- `cleanup_on_end` validation rejects unknown values
- `max_per_repo` validation rejects 0 and negative values and values > 64
- Valid YAML section loads all fields without error

---

## Done criteria

- `cfg.worktrees` is populated from YAML (or defaults) in all existing integration test configs
- Config validation tests pass
- No existing tests broken
