# BUGS

Rules:
- Bugs are tracked as tasks and must use stable IDs in format `TASK-####`.
- IDs are immutable, globally unique across `.task-management/`, and never reused.
- When a bug is scheduled for immediate work, move it to `.task-management/TODO.md` and keep the same ID.
- When a bug is deferred as general work, move it to `.task-management/BACKLOG.md` and keep the same ID.
- When a bug is fixed, remove it from this file and append it to `.task-management/DONE.md`.
- When a bug report is invalid/obsolete, remove it from this file and append it to `.task-management/REMOVED.md` with reason.

## Bug backlog

- [TASK-0042] [Critical] `!c ps` crashes with AttributeError on every invocation.
  - `routing/router.py` `handle_ps` formatting loop references `s.command` but `JobStatus` has no `command` field.
  - Raises `AttributeError` every time `!c ps` is called; command is entirely broken in production.
  - No test covers the `handle_ps` formatting path, so the crash went undetected.
  - Fix: remove `{s.command}` from the format string, or add `command: str = ""` to `JobStatus`.

- [TASK-0043] [High] Blocking `os.write()` on PTY fd can freeze the entire event loop.
  - `codex.py:182` — when the PTY buffer is full (Codex not consuming stdin), `os.write()` blocks indefinitely, stalling heartbeats, Discord dispatch, and all other active sessions.
  - Fix: wrap with `run_in_executor` or set the fd non-blocking with `fcntl.F_SETFL | os.O_NONBLOCK`.

- [TASK-0044] [High] Fire-and-forget `_waiter` task can be GC'd before `on_exit` runs.
  - `codex.py:339` — `asyncio.create_task(_waiter())` drops the reference immediately; Python can GC the task before it completes, silently skipping `on_exit` (session state finalisation, audit flushing, active-process cleanup).
  - Fix: store a strong reference to the task and discard it in a `done_callback`.

- [TASK-0045] [High] TOCTOU race in `_next_seq()` causes silent audit log data loss.
  - `observability/audit.py:223` — two concurrent writes to the same session directory both read the same counter value, generate the same sequence number, and overwrite each other's audit files.
  - Fix: wrap the read-increment-write in a per-directory `threading.Lock` or use `fcntl.flock`.

- [TASK-0046] [High] Repo deletion fails on symlinked subdirectories, leaving partial state.
  - `handlers/dm_admin.py:435` — manual `os.walk` + `os.rmdir` fails on directory-like symlinks (submodules, toolchain links), leaving the repo partially deleted and still visible in `!c repos`.
  - Fix: replace manual walk with `shutil.rmtree(repo_path)`.

- [TASK-0047] [High] Wrong Discord attribute used for thread detection in sink routing.
  - `platform/discord_bot.py:77` — `message.thread` is the thread *created by* the message, not the channel the message was *sent in*; replies can silently be routed to the wrong channel.
  - Fix: use `message.channel` directly; check `isinstance(message.channel, discord.Thread)` where thread detection is needed.

- [TASK-0048] [High] `_discord_repo_channel_is_private()` fails open on all error paths.
  - `routing/router.py:3044` — API exceptions, missing category, `AttributeError`, and `None`-channel all return `False` (allow access), silently granting repo access on any environmental anomaly.
  - Fix: return `True` (deny/treat as private) on ambiguous or error paths.

- [TASK-0049] [High] `repo_busy()` checks channel-wide activity instead of per-repo activity.
  - `routing/router.py:3156` — `has_active(channel_id)` returns `True` if any session in the channel is running regardless of repo; a session on `repo-a` falsely blocks destructive ops targeting `repo-b`, and per-repo contention is not correctly detected.
  - Fix: thread `repo_name` through `has_active` or implement a per-repo lock.

- [TASK-0050] [Medium] Startup DM sent to all `allowed_user_ids` when no admin list is configured.
  - `platform/discord_bot.py:32` — falls back to `allowed_user_ids` when `dm_admin_user_ids` is empty, pinging every allowed user on every restart.
  - Fix: send no startup DM unless `dm_admin_user_ids` is explicitly set, or document this prominently.

- [TASK-0051] [Medium] `handle_updates` subprocess inherits full host environment including secrets.
  - `handlers/system_helpers.py:47` — `os.environ.copy()` passed to the `npm view` subprocess, leaking `OPENAI_API_KEY`, `AWS_*`, and any other secrets in the operator's shell. The Codex runner uses a careful allowlist; this path bypasses it.
  - Fix: pass only the allowlist used in `codex.py:_merge_env`, or at minimum `{"PATH": os.environ.get("PATH", "")}`.

- [TASK-0052] [Medium] Bare `!c audit` always errors instead of showing recent entries.
  - `commands/registry.py:1191` — `parse_session_or_limit("")` returns limit `0`, immediately hitting "Limit must be >= 1". Casual use of `!c audit` with no arguments always fails.
  - Fix: treat limit `0` as "use default" (e.g., `limit = limit or 10`).

- [TASK-0053] [Medium] `!c git commit` auto-stages all tracked changes via `-a` without warning.
  - `handlers/git_helpers.py:76` — `commit -am` silently commits more than a user who staged a partial changeset intended.
  - Fix: use `commit -m` only and require explicit staging, or add a clear warning in `!c help git`.

- [TASK-0054] [Medium] Health endpoint body read silently truncated at 8192 bytes.
  - `services/health.py:79` — `reader.read(8192)` returns at most 8192 bytes; larger bodies are silently truncated with no error to the caller.
  - Fix: read only headers if the body is irrelevant (`readuntil(b"\r\n\r\n")`), or loop until EOF if the body is needed.

- [TASK-0055] [Medium] Multi-file upload path traversal check weaker than single-file.
  - `services/file_transfer.py:115` — multi-file uploads use a manual `startswith("..")` check; single-file uploads route through `resolve_repo_file_path` which also handles symlink resolution and normalisation. A crafted attachment filename could bypass the manual check.
  - Fix: route multi-file destination path construction through `resolve_repo_file_path`.

- [TASK-0056] [Medium] `on_jsonl` lambda in `run_codex` closes over `sink` by reference.
  - `routing/router.py` `run_codex` — if the active sink is replaced mid-run (thread switch, reconnect), in-flight callbacks silently write to the stale object.
  - Fix: capture the sink value at run start rather than closing over the mutable reference.

- [TASK-0057] [Low] Single-token input to `parse_session_and_prompt` always treated as session name.
  - `commands/parse.py` — `!c run hello` treats `hello` as a session name and produces an empty prompt, resulting in an error or empty Codex invocation. New users trying short prompts will always hit this.
  - Fix: if the token does not match a known session name, treat it as the start of the prompt.
