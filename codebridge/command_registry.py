"""Command registry and dispatch helpers for the router."""

from __future__ import annotations

from dataclasses import dataclass
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
    "Sessions",
    "Repo bootstrap",
    "Run control",
    "Repo helpers",
    "Queue",
)


@dataclass(frozen=True)
class CommandSpec:
    """Definition for a single command."""
    name: str
    usage: str
    description: str
    group: str
    handler: CommandHandler
    aliases: Tuple[str, ...] = ()


def build_registry() -> Tuple[Dict[str, CommandSpec], List[CommandSpec]]:
    """Return a command registry and ordered spec list."""
    specs = [
        CommandSpec("help", "help", "show this help", "General", _cmd_help),
        CommandSpec("status", "status", "show repo path and sessions", "General", _cmd_status),
        CommandSpec("stats", "stats [session]", "show usage totals", "General", _cmd_stats),
        CommandSpec("peek", "peek [session]", "show active status and last output time", "General", _cmd_peek),
        CommandSpec("config", "config", "show effective config", "General", _cmd_config),
        CommandSpec("start", "start [session]", "start a new Codex session", "Sessions", _cmd_start),
        CommandSpec("resume", "resume [session] <prompt>", "resume with prompt", "Sessions", _cmd_resume),
        CommandSpec(
            "choose",
            "choose [session] resume|replace|cancel",
            "resolve start conflict",
            "Sessions",
            _cmd_choose,
        ),
        CommandSpec("use", "use/select <session>", "set your sticky session", "Sessions", _cmd_use, aliases=("select",)),
        CommandSpec("model", "model [session] <id>", "set session model", "Sessions", _cmd_model),
        CommandSpec("models", "models [session]", "list available models via /models", "Sessions", _cmd_models),
        CommandSpec("thread", "thread [session] <id>", "set thread id", "Sessions", _cmd_thread),
        CommandSpec("spec", "spec [session]", "capture repo spec and tasks", "Repo bootstrap", _cmd_spec),
        CommandSpec("createrepo", "createrepo", "create repo in code_root and git init", "Repo bootstrap", _cmd_createrepo),
        CommandSpec("clonerepo", "clonerepo <url>", "clone GitHub repo into code_root", "Repo bootstrap", _cmd_clonerepo),
        CommandSpec(
            "copyrepo",
            "copyrepo <newname>",
            "copy repo without .git and init new repo",
            "Repo bootstrap",
            _cmd_copyrepo,
        ),
        CommandSpec("stop", "stop [session]", "send ESC then SIGINT", "Run control", _cmd_stop),
        CommandSpec("kill", "kill [session]", "force kill running process", "Run control", _cmd_kill),
        CommandSpec("/quit", "/quit [session]", "send /quit to Codex", "Run control", _cmd_quit),
        CommandSpec("showrepo", "showrepo", "list repo tree", "Repo helpers", _cmd_showrepo),
        CommandSpec("showchanges", "showchanges", "git status + diffstat", "Repo helpers", _cmd_showchanges),
        CommandSpec("tests", "tests", "run pytest -q", "Repo helpers", _cmd_tests),
        CommandSpec(
            "git",
            "git <status|log|branches|show|diff|pull|commit|push|merge>",
            "git helpers",
            "Repo helpers",
            _cmd_git,
        ),
        CommandSpec("download", "download <path>", "download a file from repo", "Repo helpers", _cmd_download),
        CommandSpec("logs", "logs [session] [n]", "show recent audit entries", "Queue", _cmd_logs),
        CommandSpec("ps", "ps", "list queued/running jobs", "Queue", _cmd_ps),
        CommandSpec("cancel", "cancel <job-id>", "cancel queued job", "Queue", _cmd_cancel),
        CommandSpec("rerun", "rerun", "requeue last job", "Queue", _cmd_rerun),
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
    lines = ["Commands:"]
    for group in _ordered_groups(grouped):
        lines.append(f"{group}:")
        for spec in grouped[group]:
            lines.append(f"{spec.usage} — {spec.description}")
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
    session = rest.strip() or router.current_session_for_user(message.author_id, message.channel_id)
    try:
        session = normalize_session(session)
    except ValueError as exc:
        await router.reply_forbidden(sink, str(exc))
        return
    await router.handle_stats(sink, session)


async def _cmd_peek(router: Any, message: MessageEvent, sink: ResponseSink, repo_name: str, repo_path: str, rest: str) -> None:
    session = rest.strip() or router.current_session_for_user(message.author_id, message.channel_id)
    try:
        session = normalize_session(session)
    except ValueError as exc:
        await router.reply_forbidden(sink, str(exc))
        return
    await router.handle_peek(sink, session)


async def _cmd_config(router: Any, message: MessageEvent, sink: ResponseSink, repo_name: str, repo_path: str, rest: str) -> None:
    await router.reply(sink, router.config_text())


async def _cmd_start(router: Any, message: MessageEvent, sink: ResponseSink, repo_name: str, repo_path: str, rest: str) -> None:
    session_name, _ = parse_session_and_prompt(rest)
    if not session_name:
        session_name = router.current_session_for_user(message.author_id, message.channel_id)
    try:
        session_name = normalize_session(session_name)
    except ValueError as exc:
        await router.reply_forbidden(sink, str(exc))
        return
    await router.handle_start(message, sink, repo_name, repo_path, session_name)


async def _cmd_resume(router: Any, message: MessageEvent, sink: ResponseSink, repo_name: str, repo_path: str, rest: str) -> None:
    session_name, prompt = parse_session_and_prompt(rest)
    if not session_name:
        session_name = router.current_session_for_user(message.author_id, message.channel_id)
    try:
        session_name = normalize_session(session_name)
    except ValueError as exc:
        await router.reply_forbidden(sink, str(exc))
        return
    await router.handle_resume(message, sink, repo_name, repo_path, session_name, prompt)


async def _cmd_choose(router: Any, message: MessageEvent, sink: ResponseSink, repo_name: str, repo_path: str, rest: str) -> None:
    choice, sess = parse_choose(rest)
    if not choice:
        await router.reply_forbidden(sink, "Usage: !c choose [session] resume|replace|cancel")
        return
    if sess:
        try:
            _ = normalize_session(sess)
        except ValueError as exc:
            await router.reply_forbidden(sink, str(exc))
            return
    await router.handle_choose(message, sink, repo_name, repo_path, sess, choice)


async def _cmd_use(router: Any, message: MessageEvent, sink: ResponseSink, repo_name: str, repo_path: str, rest: str) -> None:
    parts = rest.split()
    if not parts:
        await router.reply_forbidden(sink, "Usage: !c use <session>")
        return
    try:
        session_name = normalize_session(parts[0])
    except ValueError as exc:
        await router.reply_forbidden(sink, str(exc))
        return
    await router.handle_select_session(message, sink, session_name)


async def _cmd_model(router: Any, message: MessageEvent, sink: ResponseSink, repo_name: str, repo_path: str, rest: str) -> None:
    if not rest:
        await router.reply_forbidden(sink, "Usage: !c model [session] <model-id>")
        return
    parts = rest.split()
    session_name = router.current_session_for_user(message.author_id, message.channel_id)
    if len(parts) == 1:
        model = parts[0]
    else:
        session_name = parts[0]
        model = rest[len(parts[0]) :].strip()
    try:
        session_name = normalize_session(session_name)
    except ValueError as exc:
        await router.reply_forbidden(sink, str(exc))
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
        router.set_session_model(message.channel_id, session_name, repo_name, repo_path, model)
        await router.reply(sink, f"Model for session '{session_name}' set to {model}")
        await router.update_pinned_status(sink, message.author_id, session_name)

    if await router.has_active(message.channel_id):

        async def job() -> None:
            await apply_model()

        pos, job_id, _ = await router.coordinator.enqueue(message.channel_id, session_name, job)
        await router.reply(sink, f"Queued model change for session '{session_name}' to {model} as {job_id} (pos {pos}).")
        return

    await apply_model()


async def _cmd_models(router: Any, message: MessageEvent, sink: ResponseSink, repo_name: str, repo_path: str, rest: str) -> None:
    parts = rest.split()
    session_name = router.current_session_for_user(message.author_id, message.channel_id) or DEFAULT_SESSION
    if parts:
        session_name = parts[0]
    try:
        session_name = normalize_session(session_name)
    except ValueError as exc:
        await router.reply_forbidden(sink, str(exc))
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
    prompt = "/models"
    thread_id = existing_thread(state, channel_id, session_name)
    if thread_id:
        args = router.runner.build_resume_args(repo_path, thread_id, prompt, model)
    else:
        # If the session exists but thread id is missing, prefer resume --last to avoid creating a new session.
        if session_exists(state, channel_id, session_name):
            args = router.runner.build_resume_last_args(repo_path, prompt, model)
        else:
            args = router.runner.build_start_args(repo_path, prompt, model)

    collected: list[str] = []

    async def on_output(text: str) -> None:
        collected.append(text)

    async def job() -> None:
        await router.run_codex(message, sink, repo_name, repo_path, session_name, model, args, on_output=on_output)
        models = parse_models_from_lines(collected)
        if not models:
            await router.reply(sink, "No models parsed from /models output.")
            return
        lines = [f"Available models ({len(models)}):"] + [f"- {m}" for m in models]
        await router.reply(sink, "\n".join(lines))

    pos, job_id, _ = await router.coordinator.enqueue(channel_id, session_name, job)
    model_info = f"model {model}" if model else "default model"
    await router.reply(sink, f"Queued /models for session '{session_name}' ({model_info}) as {job_id} (pos {pos}).")


async def _cmd_thread(router: Any, message: MessageEvent, sink: ResponseSink, repo_name: str, repo_path: str, rest: str) -> None:
    session_name, thread_id = parse_session_and_id(rest)
    if not thread_id:
        await router.reply_forbidden(sink, "Usage: !c thread [session] <id>")
        return
    if session_name:
        try:
            session_name = normalize_session(session_name)
        except ValueError as exc:
            await router.reply_forbidden(sink, str(exc))
            return
    await router.handle_thread(sink, session_name, repo_name, repo_path, thread_id)


async def _cmd_spec(router: Any, message: MessageEvent, sink: ResponseSink, repo_name: str, repo_path: str, rest: str) -> None:
    session = rest.strip() or router.current_session_for_user(message.author_id, message.channel_id)
    try:
        session = normalize_session(session)
    except ValueError as exc:
        await router.reply_forbidden(sink, str(exc))
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
        await router.reply_forbidden(sink, "Usage: !c clonerepo <github-url>")
        return
    try:
        target_path = pathutil.resolve_repo_path_for_create(router.cfg.codex.code_root, repo_name)
    except Exception as exc:
        await router.reply_forbidden(sink, f"Repo error: {exc}")
        return
    await router.handle_clone_repo(message, sink, repo_name, target_path, url)


async def _cmd_copyrepo(router: Any, message: MessageEvent, sink: ResponseSink, repo_name: str, repo_path: str, rest: str) -> None:
    new_name = rest.strip()
    if not new_name:
        await router.reply_forbidden(sink, "Usage: !c copyrepo <new-repo-name>")
        return
    try:
        target_path = pathutil.resolve_repo_path_for_create(router.cfg.codex.code_root, new_name)
    except Exception as exc:
        await router.reply_forbidden(sink, f"Repo error: {exc}")
        return
    await router.handle_copy_repo(message, sink, repo_name, repo_path, new_name, target_path)


async def _cmd_stop(router: Any, message: MessageEvent, sink: ResponseSink, repo_name: str, repo_path: str, rest: str) -> None:
    session = rest.strip()
    if session:
        try:
            session = normalize_session(session)
        except ValueError as exc:
            await router.reply_forbidden(sink, str(exc))
            return
    await router.handle_stop(sink, session)


async def _cmd_kill(router: Any, message: MessageEvent, sink: ResponseSink, repo_name: str, repo_path: str, rest: str) -> None:
    session = rest.strip()
    if session:
        try:
            session = normalize_session(session)
        except ValueError as exc:
            await router.reply_forbidden(sink, str(exc))
            return
    await router.handle_kill(sink, session)


async def _cmd_quit(router: Any, message: MessageEvent, sink: ResponseSink, repo_name: str, repo_path: str, rest: str) -> None:
    session = rest.strip()
    if session:
        try:
            session = normalize_session(session)
        except ValueError as exc:
            await router.reply_forbidden(sink, str(exc))
            return
    await router.handle_quit(sink, session)


async def _cmd_showrepo(router: Any, message: MessageEvent, sink: ResponseSink, repo_name: str, repo_path: str, rest: str) -> None:
    await router.handle_showrepo(sink, repo_path)


async def _cmd_showchanges(router: Any, message: MessageEvent, sink: ResponseSink, repo_name: str, repo_path: str, rest: str) -> None:
    await router.handle_showchanges(sink, repo_path)


async def _cmd_tests(router: Any, message: MessageEvent, sink: ResponseSink, repo_name: str, repo_path: str, rest: str) -> None:
    await router.handle_tests(sink, repo_path)


async def _cmd_git(router: Any, message: MessageEvent, sink: ResponseSink, repo_name: str, repo_path: str, rest: str) -> None:
    await router.handle_git(sink, repo_path, rest)


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
        try:
            session_name = normalize_session(session_name)
        except ValueError as exc:
            await router.reply_forbidden(sink, str(exc))
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
