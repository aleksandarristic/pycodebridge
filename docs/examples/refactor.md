# Example: Parallel refactor with fan-out dispatch

This example shows **fan-out dispatch** — two agents run the same task in parallel,
each on their own branch. No `@claude` means no planning step; both agents start
immediately.

## Channel message

```
@codex @gemini refactor the auth module to use async/await throughout
```

## What happens

1. **Router intercepts** the `@codex @gemini` mentions (no `@claude` → no plan step).
2. **Task branch created**: `task/myapp/20260623-150000` from `HEAD`.
3. **Workers start in parallel** — each on a forked branch:
   - `task/myapp/20260623-150000-codex`
   - `task/myapp/20260623-150000-gemini`
   ```
   ⚙ @codex running…
   ✨ @gemini running…
   ```
4. Results come back as each agent finishes (order not guaranteed):
   ```
   ✅ @codex done — 4 file(s) changed
   ✅ @gemini done — 3 file(s) changed
   ```
5. **Aggregate summary**:
   ```
   **Dispatch complete** — 2/2 agent(s) succeeded
   • ✅ @codex — 4 file(s) changed
   • ✅ @gemini — 3 file(s) changed
   Run `!c done` to open a PR or merge.
   ```

## When to use fan-out

Fan-out is useful when you want to compare two approaches side-by-side:

- Different coding styles (Codex tends toward explicit types; Gemini toward conciseness)
- UI components where you want two visual interpretations
- Refactors where the best outcome isn't clear upfront — pick the better branch

## Comparing results

```bash
# Compare the two worker branches
git diff task/myapp/20260623-150000-codex-a1b2c3d4 task/myapp/20260623-150000-gemini-e5f6a7b8

# Preview each branch's diff against the task branch (which mirrors HEAD)
git diff task/myapp/20260623-150000..task/myapp/20260623-150000-codex-a1b2c3d4
git diff task/myapp/20260623-150000..task/myapp/20260623-150000-gemini-e5f6a7b8
```

After picking the better result, if needed merge or cherry-pick commits manually before
closing.

## Closing

```
!c done --pr
```

Opens a draft PR from the task branch. The worker branches
(`task/.../...-codex-<id>`, `task/.../...-gemini-<id>`) are deleted automatically.

> **Note** — `!c done` targets the **task branch**, not a worker branch. If you want
> to promote a specific worker's changes, merge that worker branch into the task branch
> first: `git merge task/.../...-codex-<id>` while on the task branch.
