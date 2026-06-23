# Multi-agent dispatch

Multi-agent dispatch lets you route a task to one or more AI backends in a single message.
Use `@agent` mentions to select agents; the orchestrator creates isolated git branches,
runs agents (with Claude planning first when included), and reports results back to the
channel.

## Syntax

```
@<agent> [more @agents...] <prompt>
```

**Supported agents**

| Handle    | Backend     | Strength                              |
|-----------|-------------|---------------------------------------|
| `@codex`  | OpenAI Codex CLI | Broad implementation tasks       |
| `@claude` | Claude CLI  | Planning, reasoning, code review      |
| `@gemini` | Gemini CLI  | UI / HTML / CSS, alternative opinions |

Agents can appear anywhere in the message — leading, trailing, or mixed with the prompt.

## Patterns

### Solo dispatch

One agent, one task, one branch.

```
@codex add pagination to the user list endpoint
```

### Fan-out (parallel)

Two or more agents, no `@claude`. All agents receive the same prompt and run in parallel,
each on their own branch forked from the shared task branch.

```
@codex @gemini refactor the auth module to use async/await
```

### Orchestrated (Claude plans first)

When `@claude` appears alongside other agents, Claude runs first and produces a plan.
The plan is prepended to the prompt delivered to each worker agent.

```
@claude @codex implement JWT login with refresh tokens
```

Claude writes the plan to the task branch. Codex (and any other workers) receive:
```
<original prompt>

Orchestrator plan:
<Claude's plan text>
```

## Branch lifecycle

```
HEAD
 └─ task/<repo>/<yyyymmdd-hhmmss>   ← task branch (created on first dispatch)
      ├─ task/.../...-codex-<id>     ← codex worker branch (forked per dispatch)
      └─ task/.../...-gemini-<id>    ← gemini worker branch
```

- The **task branch** persists across multiple dispatches in the same channel session.
  A second `@agent` message continues work on the same branch.
- **Worker branches** are created fresh per dispatch, forked from the task branch.
- Worktrees are removed after each agent finishes; only the branches remain.

## Closing a task

When agents are done, close the task branch with `!c done`:

```
!c done          # use default mode from config (dispatch.close_mode)
!c done --pr     # push branch and open a draft PR
!c done --merge  # merge into default branch and push
```

`--pr` posts the PR URL to the channel. `--merge` confirms after push.
In both cases, worker branches (`task/...-<agent>-<id>`) are deleted and the task branch
is cleared from session state.

## Output modes

Controlled by `dispatch.output_mode` in config:

| Mode        | Behaviour                                                   |
|-------------|-------------------------------------------------------------|
| `per_agent` | Posts a start and done/fail message per agent               |
| `aggregate` | Silent during run; posts a single summary when all are done |
| `both`      | Per-agent updates **and** an aggregate summary (default)    |

## Configuration

```yaml
dispatch:
  output_mode: both          # per_agent | aggregate | both
  close_mode: pr             # pr | merge
  plan_prompt: |
    You are an orchestrator. The user wants: {{USER_REQUEST}}
    Worker agents: {{AGENTS}}
    Write a concise implementation plan for them to follow.
    Be specific about file paths, function names, and interfaces.
```

`plan_prompt` is used only when `@claude` is dispatched alongside other agents.
`{{USER_REQUEST}}` and `{{AGENTS}}` are replaced at runtime.

## Examples

See [`docs/examples/`](examples/) for end-to-end walkthroughs:

- [login-feature.md](examples/login-feature.md) — orchestrated `@claude @codex`
- [refactor.md](examples/refactor.md) — parallel fan-out `@codex @gemini`
- [solo-claude.md](examples/solo-claude.md) — single-agent `@claude`
