# Pending Tasks

## TOC
- 61) TODO - Extend `!c status` with Codex `/status` details (issue plan)

---

61) TODO - Extend `!c status` with Codex `/status` details (issue plan)
 - Owner: TBD
 - Complexity: Very High
- Subtasks:
  - Extend `!c status` output to include parsed information from Codex `/status` output (as currently reported by Codex), e.g. context window + token usage, 5h limit, weekly limit, current directory, and any other key fields present.
  - Implement `/status` retrieval by issuing the Codex `/status` command and parsing the response into a stable, chat-friendly summary (tolerate format drift).
  - This must be an immediate command: it can run even when other jobs are already running (do not queue behind the per-channel job queue).
  - Ensure it does not mutate session state (thread id/model) and does not interfere with the currently running job.
  - Add unit tests for parsing and for the "immediate while running" behavior using fakes/mocks.
