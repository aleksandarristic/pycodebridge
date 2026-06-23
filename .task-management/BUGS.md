# BUGS

Rules:
- Bugs are tracked as tasks and must use stable IDs in format `TASK-####`.
- IDs are immutable, globally unique across `.task-management/`, and never reused.
- When a bug is scheduled for immediate work, move it to `.task-management/TODO.md` and keep the same ID.
- When a bug is deferred as general work, move it to `.task-management/BACKLOG.md` and keep the same ID.
- When a bug is fixed, remove it from this file and append it to `.task-management/DONE.md`.
- When a bug report is invalid/obsolete, remove it from this file and append it to `.task-management/REMOVED.md` with reason.

## Bug backlog

- [TASK-0108] Dispatch handoff loses successful worker edits that are not committed.
  - Reported: 2026-06-23
  - Context: The dispatch handoff design keeps worker branches as review artifacts, but `Orchestrator._run_backend()` treats success as a CLI exit code while changed-file detection only compares `base_branch` to `HEAD`. Agent CLIs can leave edited files in the worktree without creating commits, so the retained worker branch may not contain the work the agent performed.
  - Impact: A worker can successfully edit files and report live progress, but dispatch later removes the worktree and leaves behind a worker branch with no corresponding implementation changes for review or promotion.
  - Investigate: `codebridge/dispatch/orchestrator.py` worker completion, changed-file detection, and integration semantics for committed vs uncommitted worktree changes.
  - Acceptance criteria:
    - Successful worker runs preserve uncommitted file edits on the worker handoff branch before the worktree is removed, or fail loudly when dirty work cannot be preserved.
    - `files_changed` reflects committed and uncommitted worker changes.
    - Regression coverage proves an agent that writes a file without committing still leaves a useful review artifact or returns an actionable failure.

- [TASK-0111] Dispatch auto-merges worker branches and bypasses the handoff selection workflow.
  - Reported: 2026-06-23
  - Context: The dispatch task specs and examples describe worker branches as handoff artifacts for human comparison and manual promotion, but `Orchestrator.run()` now calls `_integrate_worker_results()` and merges every successful worker branch back into the task branch automatically.
  - Impact: Fan-out dispatch no longer preserves independent alternatives for explicit selection; multiple successful agents can be merged into the task branch without review, conflict policy, or an operator choosing the preferred result.
  - Investigate: `codebridge/dispatch/orchestrator.py` automatic integration added in `TASK-0105`, dispatch docs/examples, and whether close should require explicit promotion before deleting worker branches.
  - Acceptance criteria:
    - Worker branches are not merged into the task branch unless the operator explicitly promotes a result or the dispatch mode clearly requests automatic integration.
    - Fan-out handoff keeps alternatives separate until selection.
    - Regression coverage proves a fan-out dispatch leaves the task branch unchanged until an explicit promotion/close workflow accepts a worker branch.

- [TASK-0109] Repeated dispatches reuse stale per-agent worker branches.
  - Reported: 2026-06-23
  - Context: Worker branches are named `f"{task_branch}-{agent}"`. On a second dispatch in the same task/session, `WorktreeManager._worktree_add()` sees that branch already exists and checks it out instead of creating a fresh branch from the current task branch.
  - Impact: Later dispatches can run from stale worker branch state rather than the latest task branch, mixing previous worker history into new runs and violating the documented "fresh per dispatch" branch lifecycle.
  - Investigate: `codebridge/dispatch/orchestrator.py` worker branch naming, `codebridge/services/worktree.py` existing-branch fallback, and dispatch docs/examples that describe per-dispatch worker branches.
  - Acceptance criteria:
    - Each dispatch creates a unique worker branch, or existing worker branches are safely reset/recreated from the current task branch before use.
    - Repeated `@codex` dispatches in one task/session start from the latest task branch, not stale worker branch state.
    - Regression coverage exercises two sequential dispatches for the same agent and verifies branch isolation.

- [TASK-0110] Dispatch parser treats `@agent` substrings inside emails or words as agent mentions.
  - Reported: 2026-06-23
  - Context: `parse_dispatch()` uses `_MENTION_RE = re.compile(r"@([A-Za-z]+)")`, so strings such as `user@codex.com`, `foo@gemini`, or code/config text containing `@claude` can be parsed as dispatch requests. `_strip_known_mentions()` then removes the substring from the prompt.
  - Impact: Normal prompts can be accidentally routed to dispatch, and prompt text can be corrupted by mention stripping even when the user did not intend to invoke an agent.
  - Investigate: `codebridge/dispatch/parser.py`, router dispatch interception in command/plain-prompt flows, and parser tests for mention boundaries.
  - Acceptance criteria:
    - Agent mentions are recognized only as standalone Discord-style command tokens, not inside emails, identifiers, or arbitrary words.
    - Prompt stripping preserves non-dispatch text containing `@codex`, `@claude`, or `@gemini` substrings.
    - Regression coverage includes email-address and word-boundary cases.

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
