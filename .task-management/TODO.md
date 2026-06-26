# TODO (Immediate)

Rules:
- Use stable task IDs in format `TASK-####`.
- IDs are immutable and never reused.
- Tasks promoted from `.task-management/BUGS.md` keep the same ID.
- When moving a task to backlog, keep the same ID.
- When completing a task, remove it from this file and append it to `.task-management/DONE.md`.
- When dropping a task, remove it from this file and append it to `.task-management/REMOVED.md`.

## Active tasks

- [TASK-0127] Prevent `new`/replace recovery from falling back to stale backend session history.
  - Reported: 2026-06-26.
  - Context:
    - `handle_choose(..., "new")` clears only the stored `thread_id` while leaving the session record present.
    - If the fresh start dies before a new thread id is recorded, later resumes see that the session exists but has no thread id and call backend `resume_last`.
    - For Codex this is `resume --last`; for Claude this is `--continue`. Both can reattach to stale backend history after the user explicitly chose a fresh session.
  - Relevant code:
    - `codebridge/handlers/core.py::handle_choose` clears `thread_id` before starting replacement.
    - `codebridge/handlers/core.py::handle_resume` uses `build_resume_last_args` when a session record exists without a thread id.
    - `codebridge/routing/router.py::on_thread` records the new thread id only after the backend emits one.
  - Acceptance criteria:
    - Choosing `new` or `compact` marks the next run as explicitly fresh and cannot later degrade into `resume --last` / `--continue` if startup fails.
    - Session metadata needed for backend/model/effort is preserved or intentionally reset, but stale thread/history linkage is not reused.
    - Fresh-start failure leaves state in a safe, inspectable condition with a clear user-facing recovery path.
    - Tests cover failed fresh start followed by resume for Codex and Claude backends.

- [TASK-0128] Add `!c clear` channel default-session escape hatch.
  - Requested: 2026-06-26.
  - Goal: provide a programmatic operator command that clears/stops the current channel's default session without routing anything to Codex, Claude, Gemini, or any other LLM backend.
  - Intended UX:
    - `!c clear` clears the current channel scope's `default` session.
    - Optional top-level shortcut may be added as `!clear`.
    - Optional explicit form may be considered later, but the first implementation should optimize for the common default-session-only workflow.
  - Behavior:
    - Kill the tracked active process for the target session when possible.
    - Cancel queued jobs for the target session.
    - Clear pending conflicts, awaiting-input state, and sticky/default runtime state associated with the target session.
    - Remove the persisted `default` session entry from `state.json`.
    - Avoid repo resolution and backend command execution so the command still works when repo/session state is broken.
    - Return a concise status message showing what was killed, cancelled, and cleared.
  - Non-goals:
    - Do not remove backend auth/config.
    - Do not wipe Codex/Claude/Gemini global session history.
    - Do not implement PID-based orphan process discovery in this task; note clearly if no tracked process existed.
  - Relevant code:
    - Existing reset primitive: `Router.control_reset_session(channel_id, session, purge=False)`.
    - Command routing: `codebridge/commands/registry.py`.
    - Early command handling may need to happen before repo resolution in `Router._handle_command_flow`.
    - DM behavior should be considered separately from mapped repo channels.
  - Acceptance criteria:
    - `!c clear` works in a mapped repo channel even if repo resolution would fail.
    - The command does not enqueue or invoke any backend run.
    - The default session can be started fresh after clearing.
    - Tests cover active-process kill, queued-job cancellation, persisted-state removal, and no-repo-resolution behavior.
