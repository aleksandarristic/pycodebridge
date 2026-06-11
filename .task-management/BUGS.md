# BUGS

Rules:
- Bugs are tracked as tasks and must use stable IDs in format `TASK-####`.
- IDs are immutable, globally unique across `.task-management/`, and never reused.
- When a bug is scheduled for immediate work, move it to `.task-management/TODO.md` and keep the same ID.
- When a bug is deferred as general work, move it to `.task-management/BACKLOG.md` and keep the same ID.
- When a bug is fixed, remove it from this file and append it to `.task-management/DONE.md`.
- When a bug report is invalid/obsolete, remove it from this file and append it to `.task-management/REMOVED.md` with reason.

## Bug backlog

### TASK-0086: Thread messages silently dropped when parent channel not in Discord cache

**Symptom:** Bot does not respond to messages sent in a Discord thread after bot restart or in large guilds, with no error sent to the user.

**Root cause:** `discord_parent_context` (`event_context.py:26-43`) always reads `parent_id` from `channel.parent_id` (always available on a Discord Thread), but only populates `parent_name` when `channel.parent` (the full channel object) is in Discord's local cache. When `parent` is not cached, `channel_name` falls back to the thread's own name (e.g., `"task-123"`). In `handle_message` (router.py:349-352), the channel regex (e.g., `codex-(.+)`) is matched against `event.channel_name`, which is now the thread's name rather than the parent channel's name — no match, message is silently dropped.

**Fix sketch:** In `normalize_event_context`, when `parent_name` is empty, derive the channel name from the parent channel ID by looking it up on the raw Discord message object (e.g., `getattr(message.guild, 'get_channel', None)` with `parent_id`), or fall back to formatting it as `codex-<parent_id>` so the regex at least has a chance. Alternatively, skip the channel-name regex check entirely when `event.platform_thread_id` is set and `parent_id` is known — the composite `channel_id` is always correct, so repo_name can be derived from a direct channel lookup rather than a name regex match.

**Affected files:** `codebridge/routing/event_context.py`, `codebridge/routing/router.py`

