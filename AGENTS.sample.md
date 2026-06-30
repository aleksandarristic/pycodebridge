# AGENTS

## Intent
- Describe the repo goal and how Codex should operate within it.
- Call out preferred stacks or tools, but allow users to choose their weapon of choice when multiple languages/tools are viable.

## Key behaviors
- List any required commands or constraints.
- Prefer small, reviewable changes and add tests where feasible.
- If tooling or language choice is ambiguous, ask the user which weapon of choice they want for that task.

## Multi-agent dispatch
- Agent roles:
  - Codex is the default implementation agent for focused code changes, tests, and repo maintenance.
  - Claude is useful for planning, implementation, and review on broader or riskier changes.
  - Gemini is useful for UI and frontend-oriented tasks.
- Trigger dispatch from Discord by naming one or more agent handles in a prompt, for example:
  - `!c @claude plan the auth refactor, dispatch @codex`
  - `!c @codex @gemini implement the dashboard updates`
- A task branch is created on first dispatch and reused for follow-up commands in the same task lifecycle.
- Finish the task with `!c done`. Use `!c done --merge` when the branch should be merged locally instead of opened as a PR.
- Dispatch output may appear as per-agent status messages, an aggregate summary, or both depending on bridge configuration.
- Keep repo intent, constraints, commands, and conventions in this `AGENTS.md` file so every agent has the same operating context.

## Notes
- Check `.agent-env.local.md` for machine-local tooling and runtime notes.
- Treat `.agent-env.local.md` as a cache only; verify relevant commands in the
  current session before relying on it.
- Add repo-specific context to keep sessions aligned.
