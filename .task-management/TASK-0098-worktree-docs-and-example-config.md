# TASK-0098 — Docs + example config for worktree session isolation

**Branch:** `feature/worktree-session-isolation`
**Depends on:** TASK-0094 through TASK-0097
**Status:** TODO

## Goal

Update user-facing docs so someone can find, understand, and enable the worktree
feature from scratch. This is the last task in the worktree phase-1 series.

---

## Changes

### `config.example.yaml`

Uncomment and expand the `worktrees:` section added in TASK-0094. It should read:

```yaml
worktrees:
  # Give each session its own git worktree so concurrent sessions on the same
  # repo cannot interfere with each other's uncommitted changes.
  enabled: false

  # Directory where worktree copies are created.
  # Leave empty to create them as siblings of the repo directory
  # (e.g. /repos/myapp-wt-<session-key>/).
  base_dir: ""

  # Refuse to create a new session if this many worktrees already exist for
  # the repo. Protects against runaway session accumulation.
  max_per_repo: 8

  # What to do with the worktree when the session run ends.
  #   remove — delete the worktree directory (default, clean operation)
  #   keep   — leave the branch and directory for manual inspection or PR
  #   pr     — (future) push branch and open a draft PR, then remove
  cleanup_on_end: remove
```

### `README.md`

Add a new section **"Concurrent session isolation (worktrees)"** after the existing
session management section. Content to cover:

1. **The problem** — without isolation, two sessions on the same repo share one
   working directory and can clobber each other's in-progress changes.
2. **How it works** — each session gets a `git worktree` of the same repo on a
   dedicated branch (`session/<key>/<timestamp>`). The agent subprocess runs in that
   directory. The worktree (and its branch) is removed when the session run ends.
3. **Configuration** — point to the `worktrees:` block in `config.example.yaml`.
4. **Cleanup modes** — explain `remove` / `keep` / `pr` in one sentence each.
5. **Startup pruning** — on each startup, stale worktrees left by previous crashed
   sessions are pruned automatically (`git worktree prune`).

Keep it under 30 lines. No tutorial prose — bullet points are fine.

---

## Done criteria

- `config.example.yaml` has the fully documented `worktrees:` section
- `README.md` has the new section in the right place
- No new tests required for this task
