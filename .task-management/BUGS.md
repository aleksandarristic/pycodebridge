# BUGS

Rules:
- Bugs are tracked as tasks and must use stable IDs in format `TASK-####`.
- IDs are immutable, globally unique across `.task-management/`, and never reused.
- When a bug is scheduled for immediate work, move it to `.task-management/TODO.md` and keep the same ID.
- When a bug is deferred as general work, move it to `.task-management/BACKLOG.md` and keep the same ID.
- When a bug is fixed, remove it from this file and append it to `.task-management/DONE.md`.
- When a bug report is invalid/obsolete, remove it from this file and append it to `.task-management/REMOVED.md` with reason.

## Bug backlog

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
