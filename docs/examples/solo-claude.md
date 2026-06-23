# Example: Single-agent dispatch with @claude

This example shows **solo dispatch** — one agent, one task branch, straightforward.
Use this when you want Claude specifically (for reasoning-heavy tasks) without a planning
layer.

## Channel message

```
@claude add docstrings to all public functions in utils/string_utils.py
```

## What happens

1. **Router intercepts** the `@claude` mention.
2. **Task branch created**: `task/myapp/20260623-160000` from `HEAD`.
3. **Claude runs** on a worktree for that branch:
   ```
   🧠 @claude running…
   ✅ @claude done — 1 file(s) changed
   ```
4. **Aggregate summary**:
   ```
   **Dispatch complete** — 1/1 agent(s) succeeded
   • ✅ @claude — 1 file(s) changed
   Run `!c done` to open a PR or merge.
   ```

## Subsequent dispatches on the same task

The task branch persists for the session. Send another dispatch to continue:

```
@claude also add type annotations to the same file
```

Claude gets a fresh worktree forked from the existing task branch, so it builds on the
previous work. The task branch accumulates commits from each dispatch.

## Closing

```
!c done --pr
```

Opens a draft PR with all commits from all dispatches in this session.

## When to use @claude solo vs. @claude + @codex

| Use `@claude` alone | Use `@claude @codex`                     |
|---------------------|------------------------------------------|
| Code review         | Non-trivial implementation               |
| Docstrings / types  | Auth, data models, multi-file features   |
| Explaining code     | Anything benefiting from a written plan  |
| Quick fixes         | Work that would take >15 min to plan     |

Solo `@claude` skips the planning-prompt template entirely — Claude receives your raw
message and works directly. The orchestrated path adds overhead but produces better
results for complex implementations.
