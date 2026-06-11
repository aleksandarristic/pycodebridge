# TODO (Immediate)

Rules:
- Use stable task IDs in format `TASK-####`.
- IDs are immutable and never reused.
- Tasks promoted from `.task-management/BUGS.md` keep the same ID.
- When moving a task to backlog, keep the same ID.
- When completing a task, remove it from this file and append it to `.task-management/DONE.md`.
- When dropping a task, remove it from this file and append it to `.task-management/REMOVED.md`.

## Active tasks

- [TASK-0091] Add command to unpin all channel pins except the most recently added one.
  - Context: Discord channels accumulate pinned messages over time — the bot pins a status
    message after model/agent/effort changes, and users may also pin messages manually.
    Discord caps channels at 50 pins; beyond that pin operations silently fail. A housekeeping
    command is needed to trim stale pins without destroying everything.
  - Goal: implement `!c unpinold` (or `!c pins clean`) that unpins every pinned message in the
    current channel except the most recently pinned one, then reports how many were removed.
    The single survivor is the latest pin chronologically, regardless of whether it was created
    by the bot or a user.
  - Scope:
    - New `_cmd_unpinold` (or similar) function in `codebridge/commands/registry.py`, registered
      in the `CommandSpec` list under the "Utility" or "Admin" group.
    - The handler fetches all pins via `channel.pins()` (Discord returns them newest-first), keeps
      index 0, calls `msg.unpin()` on every remaining message, and replies with a summary:
      `"Unpinned N old messages. 1 pin kept."` (or `"No old pins to remove."` when ≤1 pin exists).
    - Because pin operations are Discord-only, the command must check that the underlying sink is
      a `DiscordResponseSink` (or that the channel supports pins); reply with an appropriate
      error on non-Discord platforms.
    - Update `self._pins` on the `DiscordAdapter` if any of the removed messages matched the
      adapter's tracked status message id — otherwise the adapter will try to edit a now-unpinned
      message on the next `update_pinned_status` call, which would silently re-pin it.
    - Requires the bot to have the `MANAGE_MESSAGES` permission (needed to unpin messages it
      did not send itself). Document this in the command description string.
  - Implementation notes:
    - `channel.pins()` returns a `List[discord.Message]` sorted newest-first. Index 0 is the
      most recently pinned message — that is the one to keep.
    - The `DiscordAdapter._pins` dict maps `channel_id: str → msg_id: int`. If the kept message
      is the adapter's tracked pin, no update needed. If the removed set contains the tracked pin
      id, clear `self._pins[channel_id]` so the next status update creates a fresh pin.
    - Rate limit: Discord allows ~5 pin/unpin operations per 10 seconds per channel. If there are
      many old pins, add a small `asyncio.sleep(0.5)` between unpin calls to avoid hitting the
      rate limit.
    - The command should be gated behind `AUTH_UNLOCK` (same auth level as other destructive ops).
  - Acceptance criteria:
    - `!c unpinold` with 0 or 1 existing pins replies "No old pins to remove."
    - With N > 1 pins, unpins N-1 messages and replies "Unpinned N-1 old messages. 1 pin kept."
    - If the removed set includes the adapter's tracked status pin, the adapter's `_pins` entry
      for the channel is cleared so the next status update creates a new pin cleanly.
    - On non-Discord channels, the command replies with an informative error rather than crashing.
    - The command is listed in `!c help` under an appropriate group.
