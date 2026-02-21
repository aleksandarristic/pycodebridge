"""Command registry and dispatch helpers for the router."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
import re
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Sequence, Tuple

from .command_parse import parse_choose, parse_session_and_id, parse_session_and_prompt, parse_session_or_limit
from .model_parse import parse_models_from_lines
from .router_helpers import (
    DEFAULT_SESSION,
    MAX_SESSIONS_PER_CHANNEL,
    count_active_sessions,
    existing_thread,
    normalize_session,
    session_exists,
)
from .transport import MessageEvent, ResponseSink
from .util import path as pathutil

CommandHandler = Callable[[Any, MessageEvent, ResponseSink, str, str, str], Awaitable[None]]

GROUP_ORDER = (
    "General",
    "Security",
    "Sessions",
    "Repo lifecycle",
    "Run control",
    "Repo helpers",
    "Queue",
)

AUTH_OPEN = "open"
AUTH_UNLOCK = "unlock"
AUTH_UNLOCK_GH = "unlock-gh"
AUTH_TOTP = "totp"
AUTH_MIXED = "mixed"
AUTH_LABELS = {
    AUTH_OPEN: "open",
    AUTH_UNLOCK: "unlock/default",
    AUTH_UNLOCK_GH: "unlock/gh",
    AUTH_TOTP: "totp",
    AUTH_MIXED: "mixed",
}

_MODEL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{1,63}$")
_REASONING_ALIASES = {
    "low": "low",
    "med": "medium",
    "medium": "medium",
    "high": "high",
    "extra": "extra-high",
    "extra-high": "extra-high",
    "extra-highest": "extra-high",
    "extrahigh": "extra-high",
    "xhigh": "extra-high",
}

_DEFAULT_MODELS_CACHE = os.path.expanduser("~/.codex/models_cache.json")


def _looks_like_model_id(token: str) -> bool:
    token = (token or "").strip()
    if not token:
        return False
    if len(token) < 3:
        return False
    if not _MODEL_ID_RE.match(token):
        return False
    if token.lower() in {"models", "model", "available", "default"}:
        return False
    if not any(ch in token for ch in "-._:"):
        return False
    return True


def _normalize_reasoning_level(value: str) -> str | None:
    if value is None:
        return ""
    raw = value.strip()
    if not raw:
        return ""
    token = re.sub(r"\s+", "-", raw.lower()).replace("_", "-")
    if token in {"default", "auto", "none"}:
        return ""
    return _REASONING_ALIASES.get(token)


def _read_models_cache(path: str = _DEFAULT_MODELS_CACHE) -> List[str]:
    if not path:
        return []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return []
    except json.JSONDecodeError:
        return []
    models = []
    for entry in data.get("models", []) or []:
        slug = (entry or {}).get("slug") or ""
        if _looks_like_model_id(slug):
            models.append(slug)
    return models


async def _normalize_session_or_reply(router: Any, sink: ResponseSink, session: str) -> str | None:
    try:
        return normalize_session(session)
    except ValueError as exc:
        await router.reply_forbidden(sink, str(exc))
        return None


async def _resolve_session_name(
    router: Any,
    message: MessageEvent,
    sink: ResponseSink,
    session: str,
    default_from_user: bool = True,
    default_value: str = DEFAULT_SESSION,
) -> str | None:
    if not session:
        if default_from_user:
            session = router.current_session_for_user(message.author_id, message.channel_id)
        else:
            session = default_value
    return await _normalize_session_or_reply(router, sink, session)


@dataclass(frozen=True)
class CommandSpec:
    """Definition for a single command."""
    name: str
    usage: str
    description: str
    group: str
    handler: CommandHandler
    auth: str
    aliases: Tuple[str, ...] = ()


def build_registry() -> Tuple[Dict[str, CommandSpec], List[CommandSpec]]:
    """Return a command registry and ordered spec list."""
    specs = [
        CommandSpec("help", "help", "show this help", "General", _cmd_help, AUTH_OPEN, aliases=("commands",)),
        CommandSpec("status", "status", "show repo path and sessions", "General", _cmd_status, AUTH_OPEN, aliases=("st",)),
        CommandSpec("stats", "stats [session]", "show usage totals", "General", _cmd_stats, AUTH_OPEN, aliases=("usage",)),
        CommandSpec("peek", "peek [session]", "show active status and last output time", "General", _cmd_peek, AUTH_OPEN, aliases=("pk",)),
        CommandSpec("config", "config", "show effective config", "General", _cmd_config, AUTH_UNLOCK, aliases=("cfg",)),
        CommandSpec(
            "unlock",
            "unlock [gh|all] [status|ttl]",
            "unlock command scopes for your account (status is open)",
            "Security",
            _cmd_unlock,
            AUTH_TOTP,
            aliases=("ul",),
        ),
        CommandSpec("lock", "lock [gh|all]", "clear unlock scopes for your account", "Security", _cmd_lock, AUTH_OPEN, aliases=("lk",)),
        CommandSpec("start", "start [session]", "start a new Codex session", "Sessions", _cmd_start, AUTH_UNLOCK, aliases=("run",)),
        CommandSpec("resume", "resume [session] <prompt>", "resume with prompt", "Sessions", _cmd_resume, AUTH_UNLOCK, aliases=("rs",)),
        CommandSpec(
            "choose",
            "choose [session] resume|replace|cancel",
            "resolve start conflict",
            "Sessions",
            _cmd_choose,
            AUTH_UNLOCK,
            aliases=("pick",),
        ),
        CommandSpec("use", "use <session>", "set your sticky session", "Sessions", _cmd_use, AUTH_UNLOCK, aliases=("select",)),
        CommandSpec("model", "model [session] <id> [reasoning]", "set session model", "Sessions", _cmd_model, AUTH_UNLOCK, aliases=("mdl",)),
        CommandSpec("models", "models [session]", "list available models via /model", "Sessions", _cmd_models, AUTH_OPEN, aliases=("mdls",)),
        CommandSpec("thread", "thread [session] <id>", "set thread id", "Sessions", _cmd_thread, AUTH_UNLOCK, aliases=("tid",)),
        CommandSpec("reset", "reset [session]", "reset session context", "Sessions", _cmd_reset, AUTH_UNLOCK),
        CommandSpec("spec", "spec [session]", "capture repo spec and tasks", "Sessions", _cmd_spec, AUTH_UNLOCK, aliases=("plan",)),
        CommandSpec(
            "create",
            "create",
            "create repo in code_root and git init",
            "Repo lifecycle",
            _cmd_createrepo,
            AUTH_TOTP,
            aliases=("createrepo", "new"),
        ),
        CommandSpec(
            "clone",
            "clone <url>",
            "clone GitHub repo into code_root",
            "Repo lifecycle",
            _cmd_clonerepo,
            AUTH_TOTP,
            aliases=("clonerepo",),
        ),
        CommandSpec(
            "copy",
            "copy <newname>",
            "copy repo without .git and init new repo",
            "Repo lifecycle",
            _cmd_copyrepo,
            AUTH_TOTP,
            aliases=("copyrepo", "cp"),
        ),
        CommandSpec("stop", "stop [session]", "send ESC then SIGINT", "Run control", _cmd_stop, AUTH_UNLOCK),
        CommandSpec("kill", "kill [session]", "force kill running process", "Run control", _cmd_kill, AUTH_UNLOCK),
        CommandSpec("/quit", "/quit [session]", "send /quit to Codex", "Run control", _cmd_quit, AUTH_UNLOCK),
        CommandSpec(
            "answer",
            "answer [session] -- <text> | answer <text>",
            "send input to active Codex session",
            "Run control",
            _cmd_answer,
            AUTH_UNLOCK,
            aliases=("reply",),
        ),
        CommandSpec("approve", "approve [session]", "send 'yes' to active session", "Run control", _cmd_approve, AUTH_UNLOCK),
        CommandSpec("deny", "deny [session]", "send 'no' to active session", "Run control", _cmd_deny, AUTH_UNLOCK),
        CommandSpec("wait", "wait", "show sessions awaiting input", "Run control", _cmd_wait, AUTH_UNLOCK),
        CommandSpec("show", "show", "list repo tree", "Repo helpers", _cmd_showrepo, AUTH_OPEN, aliases=("showrepo", "tree")),
        CommandSpec(
            "changes",
            "changes",
            "git status + diffstat",
            "Repo helpers",
            _cmd_showchanges,
            AUTH_OPEN,
            aliases=("showchanges",),
        ),
        CommandSpec("tests", "tests", "run pytest -q", "Repo helpers", _cmd_tests, AUTH_UNLOCK, aliases=("test",)),
        CommandSpec(
            "git",
            "git <status|log|branches|show|diff|pull|commit|push|merge>",
            "git helpers",
            "Repo helpers",
            _cmd_git,
            AUTH_MIXED,
        ),
        CommandSpec(
            "gh",
            "gh <args>",
            "GitHub CLI helper passthrough",
            "Repo helpers",
            _cmd_gh,
            AUTH_UNLOCK_GH,
        ),
        CommandSpec("download", "download <path>", "download a file from repo", "Repo helpers", _cmd_download, AUTH_UNLOCK, aliases=("dl",)),
        CommandSpec("logs", "logs [session] [n]", "show recent audit entries", "Queue", _cmd_logs, AUTH_UNLOCK, aliases=("log",)),
        CommandSpec("ps", "ps", "list queued/running jobs", "Queue", _cmd_ps, AUTH_OPEN),
        CommandSpec("cancel", "cancel <job-id>", "cancel queued job", "Queue", _cmd_cancel, AUTH_UNLOCK, aliases=("drop",)),
        CommandSpec("rerun", "rerun", "requeue last job", "Queue", _cmd_rerun, AUTH_UNLOCK, aliases=("retry",)),
    ]
    registry: Dict[str, CommandSpec] = {}
    for spec in specs:
        registry[spec.name] = spec
        for alias in spec.aliases:
            registry[alias] = spec
    return registry, specs


def render_help(specs: Sequence[CommandSpec]) -> str:
    """Render help text for the command registry."""
    grouped = _group_specs(specs)
    lines = [
        "Commands:",
        "Auth tags: [open]=no TOTP, [unlock/default]=default unlock or --totp, [unlock/gh]=gh unlock or --totp, [totp]=always --totp, [mixed]=depends on subcommand",
        "",
    ]
    for group in _ordered_groups(grouped):
        lines.append(f"{group}:")
        for spec in grouped[group]:
            alias_text = f" (aliases: {', '.join(spec.aliases)})" if spec.aliases else ""
            auth_text = AUTH_LABELS.get(spec.auth, spec.auth)
            lines.append(f"{spec.usage} — {spec.description} [{auth_text}]{alias_text}")
        lines.append("")
    return "\n".join(lines).strip()


async def dispatch(
    registry: Dict[str, CommandSpec],
    router: Any,
    message: MessageEvent,
    sink: ResponseSink,
    repo_name: str,
    repo_path: str,
    cmd: str,
    rest: str,
) -> bool:
    """Dispatch a command if present in the registry."""
    spec = registry.get(cmd)
    if not spec:
        return False
    await spec.handler(router, message, sink, repo_name, repo_path, rest)
    return True


def _group_specs(specs: Sequence[CommandSpec]) -> Dict[str, List[CommandSpec]]:
    grouped: Dict[str, List[CommandSpec]] = {}
    for spec in specs:
        grouped.setdefault(spec.group, []).append(spec)
    return grouped


def _ordered_groups(grouped: Dict[str, List[CommandSpec]]) -> Iterable[str]:
    seen = set()
    for group in GROUP_ORDER:
        if group in grouped:
            seen.add(group)
            yield group
    for group in grouped:
        if group not in seen:
            yield group


async def _cmd_help(router: Any, message: MessageEvent, sink: ResponseSink, repo_name: str, repo_path: str, rest: str) -> None:
    await router.send_help(sink)


async def _cmd_status(router: Any, message: MessageEvent, sink: ResponseSink, repo_name: str, repo_path: str, rest: str) -> None:
    await router.send_status(sink, repo_name, repo_path)


async def _cmd_stats(router: Any, message: MessageEvent, sink: ResponseSink, repo_name: str, repo_path: str, rest: str) -> None:
    session = await _resolve_session_name(router, message, sink, rest.strip())
    if not session:
        return
    await router.handle_stats(sink, session)


async def _cmd_peek(router: Any, message: MessageEvent, sink: ResponseSink, repo_name: str, repo_path: str, rest: str) -> None:
    session = await _resolve_session_name(router, message, sink, rest.strip())
    if not session:
        return
    await router.handle_peek(sink, session)


async def _cmd_unlock(router: Any, message: MessageEvent, sink: ResponseSink, repo_name: str, repo_path: str, rest: str) -> None:
    await router.handle_unlock(message, sink, rest)


async def _cmd_lock(router: Any, message: MessageEvent, sink: ResponseSink, repo_name: str, repo_path: str, rest: str) -> None:
    await router.handle_lock(message, sink, rest)


async def _cmd_config(router: Any, message: MessageEvent, sink: ResponseSink, repo_name: str, repo_path: str, rest: str) -> None:
    await router.reply(sink, router.config_text())


async def _cmd_start(router: Any, message: MessageEvent, sink: ResponseSink, repo_name: str, repo_path: str, rest: str) -> None:
    session_name, _ = parse_session_and_prompt(rest)
    session_name = await _resolve_session_name(router, message, sink, session_name)
    if not session_name:
        return
    await router.handle_start(message, sink, repo_name, repo_path, session_name)


async def _cmd_resume(router: Any, message: MessageEvent, sink: ResponseSink, repo_name: str, repo_path: str, rest: str) -> None:
    session_name, prompt = parse_session_and_prompt(rest)
    session_name = await _resolve_session_name(router, message, sink, session_name)
    if not session_name:
        return
    await router.handle_resume(message, sink, repo_name, repo_path, session_name, prompt)


async def _cmd_choose(router: Any, message: MessageEvent, sink: ResponseSink, repo_name: str, repo_path: str, rest: str) -> None:
    choice, sess = parse_choose(rest)
    if not choice:
        await router.reply_forbidden(sink, "Usage: !c choose [session] resume|replace|cancel")
        return
    if sess:
        if not await _normalize_session_or_reply(router, sink, sess):
            return
    await router.handle_choose(message, sink, repo_name, repo_path, sess, choice)


async def _cmd_use(router: Any, message: MessageEvent, sink: ResponseSink, repo_name: str, repo_path: str, rest: str) -> None:
    parts = rest.split()
    if not parts:
        await router.reply_forbidden(sink, "Usage: !c use <session>")
        return
    session_name = await _normalize_session_or_reply(router, sink, parts[0])
    if not session_name:
        return
    await router.handle_select_session(message, sink, session_name)


async def _cmd_model(router: Any, message: MessageEvent, sink: ResponseSink, repo_name: str, repo_path: str, rest: str) -> None:
    if not rest:
        await router.reply_forbidden(sink, "Usage: !c model [session] <model-id> [reasoning]")
        return
    parts = rest.split()
    session_name = router.current_session_for_user(message.author_id, message.channel_id)
    model = ""
    reasoning_raw = ""
    if len(parts) == 1:
        model = parts[0]
    else:
        candidate_reasoning = " ".join(parts[1:]).strip()
        normalized_reasoning = _normalize_reasoning_level(candidate_reasoning) if candidate_reasoning else None
        if candidate_reasoning and normalized_reasoning is not None:
            model = parts[0]
            reasoning_raw = candidate_reasoning
        elif candidate_reasoning and _looks_like_model_id(parts[0]):
            await router.reply_forbidden(
                sink,
                "Unknown reasoning level. Use low, medium, high, or extra-high.",
            )
            return
        else:
            session_name = parts[0]
            model = parts[1] if len(parts) > 1 else ""
            reasoning_raw = " ".join(parts[2:]).strip()
    session_name = await _resolve_session_name(router, message, sink, session_name)
    if not session_name:
        return
    if not model:
        await router.reply_forbidden(sink, "Model id required.")
        return
    if model.strip().lower() == "list":
        await router.reply_forbidden(
            sink,
            "Model id 'list' is not supported. Pick a real model id (try `!c models`), or set the session model back to your configured default.",
        )
        return
    reasoning = ""
    if reasoning_raw:
        normalized = _normalize_reasoning_level(reasoning_raw)
        if normalized is None:
            await router.reply_forbidden(
                sink,
                "Unknown reasoning level. Use low, medium, high, or extra-high.",
            )
            return
        reasoning = normalized
    state = router.state.load()
    if not session_exists(state, message.channel_id, session_name) and count_active_sessions(
        state, message.channel_id
    ) >= MAX_SESSIONS_PER_CHANNEL:
        await router.reply_forbidden(
            sink,
            f"Session limit reached ({MAX_SESSIONS_PER_CHANNEL}). Stop or reuse an existing session.",
        )
        return

    async def apply_model() -> None:
        router.set_session_model(message.channel_id, session_name, repo_name, repo_path, model, reasoning)
        reasoning_info = f" reasoning {reasoning}" if reasoning else ""
        await router.reply(sink, f"Model for session '{session_name}' set to {model}{reasoning_info}")
        await router.update_pinned_status(sink, message.author_id, session_name)

    if await router.has_active(message.channel_id):

        async def job() -> None:
            await apply_model()

        pos, job_id, _ = await router.coordinator.enqueue(message.channel_id, session_name, job)
        reasoning_info = f" reasoning {reasoning}" if reasoning else ""
        await router.reply(
            sink,
            f"Queued model change for session '{session_name}' to {model}{reasoning_info} as {job_id} (pos {pos}).",
        )
        return

    await apply_model()


async def _cmd_models(router: Any, message: MessageEvent, sink: ResponseSink, repo_name: str, repo_path: str, rest: str) -> None:
    parts = rest.split()
    session_name = router.current_session_for_user(message.author_id, message.channel_id) or DEFAULT_SESSION
    if parts:
        session_name = parts[0]
    session_name = await _resolve_session_name(router, message, sink, session_name, default_from_user=False)
    if not session_name:
        return

    channel_id = message.channel_id
    state = router.state.load()
    if not session_exists(state, channel_id, session_name) and count_active_sessions(state, channel_id) >= MAX_SESSIONS_PER_CHANNEL:
        await router.reply_forbidden(
            sink,
            f"Session limit reached ({MAX_SESSIONS_PER_CHANNEL}). Stop or reuse an existing session.",
        )
        return

    # Listing models should not depend on (or be blocked by) the current session's model override.
    model = ""
    reasoning = ""
    prompt = "/model"
    thread_id = existing_thread(state, channel_id, session_name)
    if thread_id:
        args = router.runner.build_resume_args(repo_path, thread_id, prompt, model, reasoning)
    else:
        # If the session exists but thread id is missing, prefer resume --last to avoid creating a new session.
        if session_exists(state, channel_id, session_name):
            args = router.runner.build_resume_last_args(repo_path, prompt, model, reasoning)
        else:
            args = router.runner.build_start_args(repo_path, prompt, model, reasoning)

    collected: list[str] = []

    async def on_output(text: str) -> None:
        collected.append(text)

    async def job() -> None:
        await router.run_codex(
            message,
            sink,
            repo_name,
            repo_path,
            session_name,
            model,
            reasoning,
            args,
            on_output=on_output,
            relay_output=False,
        )
        models = parse_models_from_lines(collected)
        cached = _read_models_cache()
        if cached:
            if models:
                filtered = [m for m in models if m in cached]
                models = filtered or cached
            else:
                models = cached
        if not models:
            await router.reply(sink, "No models parsed from /models output or local cache.")
            return
        lines = [f"Available models ({len(models)}):"] + [f"- {m}" for m in models]
        await router.reply(sink, "\n".join(lines))

    await router.coordinator.enqueue(channel_id, session_name, job)


async def _cmd_thread(router: Any, message: MessageEvent, sink: ResponseSink, repo_name: str, repo_path: str, rest: str) -> None:
    session_name, thread_id = parse_session_and_id(rest)
    if not thread_id:
        await router.reply_forbidden(sink, "Usage: !c thread [session] <id>")
        return
    if session_name:
        session_name = await _normalize_session_or_reply(router, sink, session_name)
        if not session_name:
            return
    await router.handle_thread(sink, session_name, repo_name, repo_path, thread_id)


async def _cmd_reset(router: Any, message: MessageEvent, sink: ResponseSink, repo_name: str, repo_path: str, rest: str) -> None:
    session = await _resolve_session_name(router, message, sink, rest.strip())
    if not session:
        return
    await router.handle_reset_session(sink, message.channel_id, session)


async def _cmd_spec(router: Any, message: MessageEvent, sink: ResponseSink, repo_name: str, repo_path: str, rest: str) -> None:
    session = await _resolve_session_name(router, message, sink, rest.strip())
    if not session:
        return
    await router.handle_spec(message, sink, repo_name, repo_path, session)


async def _cmd_createrepo(router: Any, message: MessageEvent, sink: ResponseSink, repo_name: str, repo_path: str, rest: str) -> None:
    try:
        target_path = pathutil.resolve_repo_path_for_create(router.cfg.codex.code_root, repo_name)
    except Exception as exc:
        await router.reply_forbidden(sink, f"Repo error: {exc}")
        return
    await router.handle_create_repo(message, sink, repo_name, target_path)


async def _cmd_clonerepo(router: Any, message: MessageEvent, sink: ResponseSink, repo_name: str, repo_path: str, rest: str) -> None:
    url = rest.strip()
    if not url:
        await router.reply_forbidden(sink, "Usage: !c clone <github-url>")
        return
    try:
        target_path = pathutil.resolve_repo_path_for_create(router.cfg.codex.code_root, repo_name)
    except Exception as exc:
        await router.reply_forbidden(sink, f"Repo error: {exc}")
        return
    await router.handle_clone_repo(message, sink, repo_name, target_path, url)


async def _cmd_copyrepo(router: Any, message: MessageEvent, sink: ResponseSink, repo_name: str, repo_path: str, rest: str) -> None:
    raw_new_name = rest.strip()
    new_name = raw_new_name
    if not new_name:
        await router.reply_forbidden(sink, "Usage: !c copy <new-repo-name>")
        return
    try:
        new_name = pathutil.normalize_repo_name(raw_new_name)
        target_path = pathutil.resolve_repo_path_for_create(router.cfg.codex.code_root, new_name)
    except Exception as exc:
        await router.reply_forbidden(sink, f"Repo error: {exc}")
        return
    await router.handle_copy_repo(message, sink, repo_name, repo_path, new_name, target_path)


async def _cmd_stop(router: Any, message: MessageEvent, sink: ResponseSink, repo_name: str, repo_path: str, rest: str) -> None:
    session = rest.strip()
    if session:
        session = await _normalize_session_or_reply(router, sink, session)
        if not session:
            return
    await router.handle_stop(sink, session)


async def _cmd_kill(router: Any, message: MessageEvent, sink: ResponseSink, repo_name: str, repo_path: str, rest: str) -> None:
    session = rest.strip()
    if session:
        session = await _normalize_session_or_reply(router, sink, session)
        if not session:
            return
    await router.handle_kill(sink, session)


async def _cmd_quit(router: Any, message: MessageEvent, sink: ResponseSink, repo_name: str, repo_path: str, rest: str) -> None:
    session = rest.strip()
    if session:
        session = await _normalize_session_or_reply(router, sink, session)
        if not session:
            return
    await router.handle_quit(sink, session)


async def _parse_answer_args(router: Any, message: MessageEvent, sink: ResponseSink, rest: str) -> tuple[str, str] | None:
    rest = (rest or "").strip()
    if not rest:
        await router.reply_forbidden(sink, "Usage: !c answer [session] -- <text>  or  !c answer <text>")
        return None
    session = router.current_session_for_user(message.author_id, message.channel_id)
    text = rest
    if "--" in rest:
        left, right = rest.split("--", 1)
        text = right.strip()
        left = left.strip()
        if left:
            session = await _normalize_session_or_reply(router, sink, left)
            if not session:
                return None
    if not text.strip():
        await router.reply_forbidden(sink, "Answer text required.")
        return None
    return session, text.strip()


async def _cmd_answer(router: Any, message: MessageEvent, sink: ResponseSink, repo_name: str, repo_path: str, rest: str) -> None:
    parsed = await _parse_answer_args(router, message, sink, rest)
    if not parsed:
        return
    session, text = parsed
    await router.handle_answer(message, sink, session, text)


async def _cmd_approve(router: Any, message: MessageEvent, sink: ResponseSink, repo_name: str, repo_path: str, rest: str) -> None:
    session = rest.strip()
    if session:
        session = await _normalize_session_or_reply(router, sink, session)
        if not session:
            return
    else:
        session = router.current_session_for_user(message.author_id, message.channel_id)
    await router.handle_answer(message, sink, session, "yes")


async def _cmd_deny(router: Any, message: MessageEvent, sink: ResponseSink, repo_name: str, repo_path: str, rest: str) -> None:
    session = rest.strip()
    if session:
        session = await _normalize_session_or_reply(router, sink, session)
        if not session:
            return
    else:
        session = router.current_session_for_user(message.author_id, message.channel_id)
    await router.handle_answer(message, sink, session, "no")


async def _cmd_wait(router: Any, message: MessageEvent, sink: ResponseSink, repo_name: str, repo_path: str, rest: str) -> None:
    await router.handle_wait(message, sink)


async def _cmd_showrepo(router: Any, message: MessageEvent, sink: ResponseSink, repo_name: str, repo_path: str, rest: str) -> None:
    await router.handle_showrepo(sink, repo_path)


async def _cmd_showchanges(router: Any, message: MessageEvent, sink: ResponseSink, repo_name: str, repo_path: str, rest: str) -> None:
    await router.handle_showchanges(sink, repo_path)


async def _cmd_tests(router: Any, message: MessageEvent, sink: ResponseSink, repo_name: str, repo_path: str, rest: str) -> None:
    await router.handle_tests(sink, repo_path)


async def _cmd_git(router: Any, message: MessageEvent, sink: ResponseSink, repo_name: str, repo_path: str, rest: str) -> None:
    await router.handle_git(sink, repo_path, rest)


async def _cmd_gh(router: Any, message: MessageEvent, sink: ResponseSink, repo_name: str, repo_path: str, rest: str) -> None:
    await router.handle_gh(sink, repo_path, rest)


async def _cmd_download(router: Any, message: MessageEvent, sink: ResponseSink, repo_name: str, repo_path: str, rest: str) -> None:
    if not rest:
        await router.reply_forbidden(sink, "Usage: !c download <path>")
        return
    await router.handle_download(sink, repo_path, rest.strip())


async def _cmd_logs(router: Any, message: MessageEvent, sink: ResponseSink, repo_name: str, repo_path: str, rest: str) -> None:
    session_name, limit = parse_session_or_limit(rest)
    if limit <= 0:
        limit = 5
    if session_name:
        session_name = await _normalize_session_or_reply(router, sink, session_name)
        if not session_name:
            return
    await router.handle_logs(sink, session_name, limit)


async def _cmd_ps(router: Any, message: MessageEvent, sink: ResponseSink, repo_name: str, repo_path: str, rest: str) -> None:
    await router.handle_ps(sink)


async def _cmd_cancel(router: Any, message: MessageEvent, sink: ResponseSink, repo_name: str, repo_path: str, rest: str) -> None:
    job_id = rest.strip()
    if not job_id:
        await router.reply_forbidden(sink, "Usage: !c cancel <job-id>")
        return
    await router.handle_cancel(sink, job_id)


async def _cmd_rerun(router: Any, message: MessageEvent, sink: ResponseSink, repo_name: str, repo_path: str, rest: str) -> None:
    await router.handle_rerun(sink)
