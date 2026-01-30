# AGENTS

## Intent
- Build and maintain the Python service that bridges transport channels (`codex-<repo>`) to Codex CLI sessions in the matching repo under `code_root`.
- One Codex session per channel per session name; queue requests sequentially; stream Codex JSONL output back to Discord.
- Persist state and audit logs per channel/session/thread; provide explicit run control (stop/kill/quit) and repo helpers.
- Keep Router transport-agnostic via `MessageEvent` + `ResponseSink`; adapters map platform events (Discord, future Slack) into these interfaces.

## Key behaviors
- Commands: start, resume, /quit, stop, kill, choose resume|replace|cancel, use/select, model, thread, help/status/config, logs, stats/peek, showrepo/showchanges/tests, git helpers, ps/cancel/rerun, repo bootstrap (createrepo/clonerepo/copyrepo/spec).
- Access control: enforce channel name regex and optional `allowed_user_ids`; DM admin commands gated by config allowlist.
- Session lifecycle: resume by stored thread id with fallback to `resume --last`; max 3 active sessions per channel; sticky session per user.
- Security: repo path containment, reject traversal, require `.git`, sanitize identifiers used in filesystem paths.
- Formatting: strip ANSI/control codes, chunk to Discord limits, wrap diffs in ```diff fences, prefix prompts as `Codex asks:`.
- Denials: respond with "I'm sorry, Dave. I'm afraid I can't do that." plus a fenced detail block.

## Files to consult
- `instructions/instructions.md` — full Python implementation spec.
- `instructions/tasks/pending.md` — active task list.
- `instructions/tasks/done.md` — completed tasks.
- `instructions/tasks/removed.md` — removed tasks.
- `instructions/tasks/backlog.md` — backlog for future tasks to promote into pending.
- Each new task must include a `Complexity:` grade (Very Low/Low/Medium/High/Very High).
- `instructions/progress_log.md` — progress log entries (append new milestones here).
- `docs/architecture.mmd` — mermaid architecture diagram.
- `<GO_CODEBRIDGE>/AGENTS.md` and `<GO_CODEBRIDGE>/instructions` — Go reference for intended behavior.
- `.codex/skills/README.md` and skill `SKILL.md` files — use when tasks match their descriptions.

## Workflow note
- When unsure about behavior, check the Go implementation in `<GO_CODEBRIDGE>` first. If the Go approach is not suitable for Python, ask the user for guidance before diverging.
- Move tasks between `instructions/tasks/*.md` as status changes and append to `instructions/progress_log.md` when completing milestones.
- Use relevant skills under `.codex/skills` when tasks align (refactor, API changes, packaging/deps, performance triage, architecture review).
