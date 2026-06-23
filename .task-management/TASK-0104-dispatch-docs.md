# TASK-0104 — Dispatch documentation and worked examples

**Branch:** `feature/dispatch-orchestrator`
**Status:** TODO

## Goal

Write the `docs/` directory with the mental model, command reference, and three
self-contained scenario walkthroughs. Update README to link into docs. Update both
example configs with the `dispatch:` section.

---

## Changes

### `docs/dispatch.md` (new file)

Cover:
- **Mental model** — agent roles (Codex=implementation, Claude=plan+implement+review,
  Gemini=UI), task branch concept, worker fork branches, how parallel and sequential
  dispatch differ
- **@mention syntax** — how `@agent` is parsed, what happens with multiple mentions,
  what "orchestrated" means (Claude leads)
- **Task branch lifecycle** — created on first dispatch, persists across follow-up
  commands, closed with `!c done`
- **Output modes** — what the bot posts for `per_agent`, `aggregate`, `both`
- **Close modes** — `pr` vs `merge`, how to override per-invocation

### `docs/examples/login-feature.md` (new file)

Annotated Discord transcript for the mixed pattern:

```
User:    !c @claude plan a login feature, dispatch @codex and @gemini
Bot:     🧠 @claude running…
Bot:     🧠 @claude done — plan committed (task/myapp/20260623-1430)
Bot:     ⚙ @codex running…  ✨ @gemini running…
Bot:     ⚙ @codex done — 6 files changed
Bot:     ✨ @gemini done — 3 files changed
Bot:     **Dispatch complete** — 3/3 agents succeeded
         • 🧠 @claude — plan committed
         • ⚙ @codex — 6 files changed
         • ✨ @gemini — 3 files changed
         Run `!c done` to open a PR, or `!c done --merge` to merge locally.

User:    !c @claude review what codex and gemini did
Bot:     🧠 @claude running…
Bot:     🧠 @claude done — review notes committed

User:    !c done
Bot:     📬 PR opened: https://github.com/org/repo/pull/42
```

Annotations explain each step: what branch is active, what worktrees exist, what commits
were made.

### `docs/examples/refactor.md` (new file)

Sequential pattern:
```
User:    !c @codex refactor the auth module to use the new config
Bot:     ⚙ @codex running…
Bot:     ⚙ @codex done — 8 files changed

User:    !c @claude review and clean up
Bot:     🧠 @claude running…
Bot:     🧠 @claude done — 2 files changed

User:    !c done --merge
Bot:     ✅ Merged and pushed to main
```

### `docs/examples/solo-claude.md` (new file)

Claude as sole implementer on a complex cross-file task:
```
User:    !c @claude refactor all error handling to use the new ErrorResult type
Bot:     🧠 @claude running…
Bot:     🧠 @claude done — 12 files changed

User:    !c done
Bot:     📬 PR opened: https://github.com/org/repo/pull/43
```

Notes on when to prefer Claude over Codex for implementation.

### `docs/dispatch-reference.md` (new file)

Full command reference:
- `!c @agent <prompt>` — solo dispatch
- `!c @agent1 @agent2 <prompt>` — parallel fan-out
- `!c @claude <prompt>, dispatch @agent1 @agent2` — orchestrated fan-out
- `!c done` — close task with configured default mode
- `!c done --pr` — force PR mode
- `!c done --merge` — force merge mode
- Error cases: no active task, git push fails, gh not installed

Config reference table: `dispatch.output_mode`, `dispatch.close_mode`, `dispatch.plan_prompt`.

### `README.md`

Add "## Multi-agent dispatch" section (before "## Concurrent session isolation") with
2-paragraph summary and links to `docs/dispatch.md` and `docs/examples/`.

### `config.example.yaml` and `config.docker.example.yaml`

Confirm `dispatch:` section is present (added in TASK-0100); add inline link comment
pointing to `docs/dispatch.md`.

---

## Done criteria

- `docs/dispatch.md` covers mental model, syntax, lifecycle, output modes, close modes
- Three example walkthroughs cover mixed, sequential, and solo-claude patterns
- `docs/dispatch-reference.md` covers all commands and config keys
- README links into docs
- No broken Markdown links
