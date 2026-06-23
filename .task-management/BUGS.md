# BUGS

Rules:
- Bugs are tracked as tasks and must use stable IDs in format `TASK-####`.
- IDs are immutable, globally unique across `.task-management/`, and never reused.
- When a bug is scheduled for immediate work, move it to `.task-management/TODO.md` and keep the same ID.
- When a bug is deferred as general work, move it to `.task-management/BACKLOG.md` and keep the same ID.
- When a bug is fixed, remove it from this file and append it to `.task-management/DONE.md`.
- When a bug report is invalid/obsolete, remove it from this file and append it to `.task-management/REMOVED.md` with reason.

## Bug backlog

- [TASK-0107] Worktree cleanup leaves stale Git worktree entries when `worktrees.base_dir` is outside the repo parent.
  - Reported: 2026-06-23
  - Context: `WorktreeManager.remove()` tries to rediscover the owning repo by scanning siblings of the worktree path. When `base_dir` points to an external directory, the original repo is not a sibling, so cleanup deletes the directory with `shutil.rmtree()` without running `git worktree remove`.
  - Impact: Git retains a prunable worktree entry for a non-existent path; `count_for_repo()` still counts it until prune runs, which can incorrectly hit `max_per_repo` and block new sessions.
  - Evidence: A local reproduction with an external `base_dir` showed `count_for_repo()` remained `1` after `remove()`, and `git worktree list --porcelain` reported `prunable gitdir file points to non-existent location`.
  - Investigate: `codebridge/services/worktree.py` repo ownership tracking, startup prune behavior, and `tests/test_worktree_manager.py` base-dir cleanup coverage.
  - Acceptance criteria:
    - Removing an externally hosted worktree runs `git worktree remove` against the correct repo.
    - `count_for_repo()` returns `0` immediately after cleanup for worktrees created under `base_dir`.
    - Regression coverage covers external `base_dir` cleanup and max-per-repo behavior after removal.

- [TASK-0090] Gemini streamed Discord output chunks can arrive out of order.
  - Reported: 2026-06-11
  - Context: In a Discord channel using `!agent gemini`, the assistant response was delivered as chunks in the wrong order:
    - Observed: `🔓 Hello! How can I help you with the s` followed by `Gemini asks: ajt repository today?`
    - Expected: `Gemini asks: Hello! How can I help you with the sajt repository today?`
  - Impact: Users see scrambled Gemini responses when streamed text is split across multiple Discord sends.
  - Investigate: Gemini stream parsing, output coalescing/flushing, and Discord send ordering for backend-prefixed assistant messages.
  - Acceptance criteria:
    - Gemini streamed assistant text preserves source order across chunk boundaries.
    - Backend ask prefix is emitted exactly once at the beginning of the relayed response.
    - Regression coverage reproduces split Gemini output and verifies Discord send order.
