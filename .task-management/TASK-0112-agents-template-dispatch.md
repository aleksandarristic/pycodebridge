# TASK-0112 — Update AGENTS.sample.md with dispatch workflow section; wire into docker config

**Status:** DONE

## Goal

Newly created repos should arrive with an AGENTS.md that explains the multi-agent
dispatch workflow so any agent (Claude, Codex, Gemini) knows how to operate within it
without the user having to explain it manually.

Also fix `config.docker.example.yaml` which currently sets `agents_template: ""`,
meaning Docker deployments seed no AGENTS.md at all.

---

## Changes

### `AGENTS.sample.md`

Add a `## Multi-agent dispatch` section covering:
- The three agent roles: Codex (implementation), Claude (plan + implement + review),
  Gemini (UI/frontend tasks)
- How to trigger dispatch from Discord: `!c @claude plan X, dispatch @codex`
  or `!c @codex @gemini implement X`
- Task branch lifecycle: created on first dispatch, persists across follow-up
  commands, closed with `!c done`
- Output modes: per-agent status messages and/or aggregate summary
- Close modes: `!c done` (PR), `!c done --merge` (merge locally)
- That `AGENTS.md` in the repo is the place to document repo intent,
  constraints, and conventions for agents to follow

### `config.docker.example.yaml`

Change:
```yaml
agents_template: ""
```
to:
```yaml
agents_template: "./AGENTS.sample.md"
```

---

## Done criteria

- `AGENTS.sample.md` contains a clear `## Multi-agent dispatch` section
- An agent reading it understands the workflow without additional prompting
- `config.docker.example.yaml` seeds AGENTS.md on `!c create`
- No test changes required (template content is not unit-tested)
