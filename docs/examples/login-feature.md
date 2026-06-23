# Example: Implement login with orchestrated dispatch

This example shows **orchestrated dispatch** — `@claude` plans first, then `@codex`
implements. The two agents work on isolated branches but share a task branch as the
handoff point.

## Channel message

```
@claude @codex implement JWT login with refresh tokens
```

## What happens

1. **Router intercepts** the `@claude @codex` mentions and calls the orchestrator.
2. **Task branch created**: `task/myapp/20260623-143012` forked from `HEAD`.
3. **Claude planning step** — Claude runs on the task branch, writes a plan, commits it.
   The channel sees:
   ```
   🧠 @claude running…
   ✅ @claude done — 2 file(s) changed
   ```
4. **Codex worker** — receives the original prompt with Claude's plan appended,
   runs on `task/myapp/20260623-143012-codex` (forked from the task branch).
   ```
   ⚙ @codex running…
   ✅ @codex done — 6 file(s) changed
   ```
5. **Aggregate summary** (with `output_mode: both`):
   ```
   **Dispatch complete** — 1/1 agent(s) succeeded
   • ✅ @codex — 6 file(s) changed
   Run `!c done` to open a PR or merge.
   ```

## Worker prompt (what Codex receives)

```
implement JWT login with refresh tokens

Orchestrator plan:
## Plan

### Files to create
- `auth/jwt.py` — JWT encode/decode, 15-min access token, 7-day refresh token
- `auth/middleware.py` — FastAPI dependency that validates Bearer tokens
- `api/routes/auth.py` — `/login`, `/refresh`, `/logout` endpoints

### Interfaces
- `create_tokens(user_id: str) -> dict[str, str]`
- `verify_token(token: str) -> str | None`  (returns user_id or None)

### Notes
- Store refresh tokens in Redis with TTL matching token lifetime
- Return 401 on expired/invalid token, not 500
```

## Closing the task

Once you review the branches:

```
# Option A: open a draft PR for review
!c done --pr

# Option B: merge directly (use for small trusted changes)
!c done --merge
```

With `--pr`, the channel posts:
```
📬 PR opened: https://github.com/acme/myapp/pull/47 — review and merge on GitHub
```

## What to check before closing

- `git log task/myapp/20260623-143012` — Claude's planning commits
- `git log task/myapp/20260623-143012-codex-a1b2c3d4` — Codex's implementation
- `git diff task/myapp/20260623-143012..task/myapp/20260623-143012-codex-a1b2c3d4` — full diff

If Codex's branch looks good but you want to cherry-pick plan commits too, merge the
task branch into the worker branch manually before running `!c done`.
