# AGENTS

## Intent
- Build and maintain the Python service that bridges Discord channels (`codex-<repo>`) to Codex CLI sessions in the matching repo under `code_root`.
- One Codex session per channel per session name; queue requests sequentially; stream Codex JSONL output back to Discord.
- Persist state and audit logs per channel/session/thread; provide explicit run control (stop/kill/quit) and repo helpers.

## Key behaviors
- Commands: start, resume, /quit, stop, kill, choose resume|replace|cancel, use/select, model, thread, help/status/config, logs, stats/peek, showrepo/showchanges/tests, git helpers, ps/cancel/rerun, repo bootstrap (createrepo/clonerepo/copyrepo/spec).
- Access control: enforce channel name regex and optional `allowed_user_ids`; DM admin commands gated by config allowlist.
- Session lifecycle: resume by stored thread id with fallback to `resume --last`; max 3 active sessions per channel; sticky session per user.
- Security: repo path containment, reject traversal, require `.git`, sanitize identifiers used in filesystem paths.
- Formatting: strip ANSI/control codes, chunk to Discord limits, wrap diffs in ```diff fences, prefix prompts as `Codex asks:`.
- Denials: respond with "I'm sorry, Dave. I'm afraid I can't do that." plus a fenced detail block.

## Files to consult
- `instructions/instructions.md` — full Python implementation spec.
- `instructions/tasks.md` — task list and progress log (mark tasks with `- DONE`).
- `/home/leka/Code/codebridge/AGENTS.md` and `/home/leka/Code/codebridge/instructions` — Go reference for intended behavior.

## Workflow note
- When unsure about behavior, check the Go implementation in `/home/leka/Code/codebridge` first. If the Go approach is not suitable for Python, ask the user for guidance before diverging.
- Update `instructions/tasks.md` (task status and progress log) when completing milestones.
