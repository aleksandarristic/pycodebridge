"""Command registry and dispatch helpers for the router."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
import re
from typing import Any, Awaitable, Callable, Dict, List, Sequence, Tuple

from .parse import parse_choose, parse_session_and_id, parse_session_and_prompt, parse_session_or_limit
from . import help as help_renderer
from .model import parse_models_from_lines
from ..routing.helpers import (
    DEFAULT_SESSION,
    MAX_SESSIONS_PER_CHANNEL,
    count_active_sessions,
    existing_thread,
    normalize_session,
    session_exists,
)
from ..platform.transport import MessageEvent, ResponseSink
from ..util import path as pathutil

CommandHandler = Callable[[Any, MessageEvent, ResponseSink, str, str, str], Awaitable[None]]

AUTH_OPEN = "open"
AUTH_UNLOCK = "unlock"
AUTH_UNLOCK_GH = "unlock-gh"
AUTH_TOTP = "totp"
AUTH_MIXED = "mixed"
SURFACE_CORE = "core"
SURFACE_SUPPORT = "support"
SURFACE_ADVANCED = "advanced"
SURFACE_ADMIN = "admin"

COMMAND_MODEL_META: Dict[str, Dict[str, str]] = {
    "help": {"surface": SURFACE_CORE, "namespace": "general"},
    "status": {"surface": SURFACE_CORE, "namespace": "general"},
    "stats": {"surface": SURFACE_ADMIN, "namespace": "diag"},
    "budget": {"surface": SURFACE_ADMIN, "namespace": "diag"},
    "peek": {"surface": SURFACE_ADVANCED, "namespace": "diag"},
    "updates": {"surface": SURFACE_ADVANCED, "namespace": "diag"},
    "health": {"surface": SURFACE_ADVANCED, "namespace": "diag"},
    "config": {"surface": SURFACE_ADMIN, "namespace": "admin"},
    "options": {"surface": SURFACE_ADMIN, "namespace": "admin"},
    "unlock": {"surface": SURFACE_ADMIN, "namespace": "admin"},
    "lock": {"surface": SURFACE_ADMIN, "namespace": "admin"},
    "start": {"surface": SURFACE_CORE, "namespace": "session"},
    "resume": {"surface": SURFACE_CORE, "namespace": "session"},
    "choose": {"surface": SURFACE_SUPPORT, "namespace": "session"},
    "use": {"surface": SURFACE_CORE, "namespace": "session"},
    "agent": {"surface": SURFACE_ADVANCED, "namespace": "session"},
    "model": {"surface": SURFACE_ADVANCED, "namespace": "session"},
    "models": {"surface": SURFACE_ADVANCED, "namespace": "session"},
    "thread": {"surface": SURFACE_ADMIN, "namespace": "session"},
    "reset": {"surface": SURFACE_CORE, "namespace": "session"},
    "workflow": {"surface": SURFACE_SUPPORT, "namespace": "session"},
    "purge": {"surface": SURFACE_ADMIN, "namespace": "session"},
    "session": {"surface": SURFACE_ADMIN, "namespace": "session"},
    "spec": {"surface": SURFACE_ADVANCED, "namespace": "session"},
    "create": {"surface": SURFACE_ADMIN, "namespace": "repo-admin"},
    "clone": {"surface": SURFACE_ADMIN, "namespace": "repo-admin"},
    "copy": {"surface": SURFACE_ADMIN, "namespace": "repo-admin"},
    "stop": {"surface": SURFACE_CORE, "namespace": "run"},
    "interrupt": {"surface": SURFACE_SUPPORT, "namespace": "run"},
    "kill": {"surface": SURFACE_ADMIN, "namespace": "run"},
    "/quit": {"surface": SURFACE_SUPPORT, "namespace": "run"},
    "steer": {"surface": SURFACE_CORE, "namespace": "run"},
    "answer": {"surface": SURFACE_CORE, "namespace": "run"},
    "approve": {"surface": SURFACE_CORE, "namespace": "run"},
    "deny": {"surface": SURFACE_CORE, "namespace": "run"},
    "wait": {"surface": SURFACE_CORE, "namespace": "run"},
    "show": {"surface": SURFACE_CORE, "namespace": "repo"},
    "changes": {"surface": SURFACE_CORE, "namespace": "repo"},
    "tests": {"surface": SURFACE_CORE, "namespace": "repo"},
    "branch": {"surface": SURFACE_CORE, "namespace": "repo"},
    "git": {"surface": SURFACE_CORE, "namespace": "repo"},
    "gh": {"surface": SURFACE_CORE, "namespace": "repo"},
    "download": {"surface": SURFACE_ADVANCED, "namespace": "repo"},
    "logs": {"surface": SURFACE_ADMIN, "namespace": "diag"},
    "audit": {"surface": SURFACE_ADMIN, "namespace": "diag"},
    "ps": {"surface": SURFACE_SUPPORT, "namespace": "diag"},
    "cancel": {"surface": SURFACE_SUPPORT, "namespace": "run"},
    "rerun": {"surface": SURFACE_ADVANCED, "namespace": "run"},
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
_TTL_RE = re.compile(r"^(\d+)\s*([mhd])$", re.IGNORECASE)

_DEFAULT_MODELS_CACHE = os.path.expanduser("~/.codex/models_cache.json")
_WORKFLOW_SPECS: Dict[str, Dict[str, str]] = {
    "inspect": {
        "summary": "inspect repo state before changing anything",
        "prompt": (
            "Inspect the current repository state before making changes. "
            "Summarize the current branch, working tree status, relevant files, and immediate risks. "
            "Do not make code changes unless they are clearly required to answer the request."
        ),
    },
    "fix": {
        "summary": "investigate and fix a focused problem",
        "prompt": (
            "Investigate and fix the requested problem in this repository. "
            "Start by reproducing or locating the issue, make the smallest safe change, run targeted validation, "
            "and summarize the fix plus any remaining risk."
        ),
    },
    "review": {
        "summary": "review current changes with findings first",
        "prompt": (
            "Review the current repository state or pending changes with a code-review mindset. "
            "Prioritize bugs, behavioral regressions, risky assumptions, and missing tests. "
            "Present findings first with file references and keep summary second."
        ),
    },
    "ship": {
        "summary": "prepare current work for handoff",
        "prompt": (
            "Prepare the current work for handoff. "
            "Check the working tree state, run or identify targeted validation, summarize user-visible changes and risks, "
            "and note the next release or follow-up step without expanding scope."
        ),
    },
}


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


def _parse_workflow_request(rest: str) -> tuple[str, str, str]:
    """Parse workflow requests into `(session, workflow, focus)`."""
    raw = (rest or "").strip()
    if not raw:
        return "", "", ""
    parts = raw.split()
    first = parts[0].lower()
    if first in {"list", "ls"} and len(parts) == 1:
        return "", "list", ""
    if first in _WORKFLOW_SPECS:
        focus = raw[len(parts[0]) :].strip()
        return "", first, focus
    if len(parts) >= 2 and parts[1].lower() in _WORKFLOW_SPECS:
        prefix = f"{parts[0]} {parts[1]}"
        focus = raw[len(prefix) :].strip()
        return parts[0], parts[1].lower(), focus
    return "", "", ""


def _build_workflow_prompt(workflow: str, repo_name: str, focus: str) -> str:
    """Render the built-in workflow prompt for Codex."""
    spec = _WORKFLOW_SPECS[workflow]
    lines = [
        spec["prompt"],
        f"Repository: {repo_name}.",
        "Follow the repository AGENTS.md and any repo-local instructions.",
    ]
    detail = (focus or "").strip()
    if detail.startswith("--"):
        detail = detail[2:].strip()
    if detail:
        lines.append(f"Focus: {detail}")
    return "\n".join(lines)


def _render_workflow_listing(prefix: str = "!c") -> str:
    """Render built-in workflow macro help."""
    pref = (prefix or "!c").strip()
    lines = [
        "Built-in workflows:",
        *[f"- `{name}`: {spec['summary']}" for name, spec in _WORKFLOW_SPECS.items()],
        f"Usage: `{pref} workflow [session] <{'|'.join(_WORKFLOW_SPECS.keys())}> [focus]`",
        "Examples:",
        f"- `{pref} workflow inspect auth flow`",
        f"- `{pref} workflow review`",
        f"- `{pref} workflow fix failing tests`",
    ]
    return "\n".join(lines)


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


def _current_session(router: Any, message: MessageEvent, default_value: str = DEFAULT_SESSION) -> str:
    if hasattr(router, "current_session_for_event"):
        return router.current_session_for_event(message)
    try:
        return router.current_session_for_user(message.author_id, message.channel_id, default_value)
    except TypeError:
        return router.current_session_for_user(message.author_id, message.channel_id)


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
            session = _current_session(router, message, default_value)
        else:
            session = default_value
    normalized = await _normalize_session_or_reply(router, sink, session)
    if not normalized:
        return None
    if hasattr(router, "resolve_scoped_session_for_event"):
        try:
            return router.resolve_scoped_session_for_event(message, normalized)
        except ValueError as exc:
            await router.reply_forbidden(sink, str(exc))
            return None
    return normalized


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
        CommandSpec("help", "help [command]", "show this help", "General", _cmd_help, AUTH_OPEN, aliases=("commands",)),
        CommandSpec("status", "status", "show repo path and sessions", "General", _cmd_status, AUTH_OPEN, aliases=("st",)),
        CommandSpec("stats", "stats [session]", "show usage totals", "General", _cmd_stats, AUTH_OPEN, aliases=("usage",)),
        CommandSpec(
            "budget",
            "budget [status] | budget set <channel|user|session|run> <soft> <hard> | budget clear [channel|user|session|run|all]",
            "usage budget visibility and controls",
            "General",
            _cmd_budget,
            AUTH_OPEN,
            aliases=("budgets",),
        ),
        CommandSpec("peek", "peek [session]", "show active status and last output time", "General", _cmd_peek, AUTH_OPEN, aliases=("pk",)),
        CommandSpec(
            "updates",
            "updates",
            "check installed Codex CLI vs latest npm release",
            "General",
            _cmd_updates,
            AUTH_OPEN,
            aliases=("update", "version", "u"),
        ),
        CommandSpec(
            "health",
            "health",
            "show runtime diagnostics",
            "General",
            _cmd_health,
            AUTH_OPEN,
            aliases=("diag",),
        ),
        CommandSpec("config", "config", "show effective config", "General", _cmd_config, AUTH_UNLOCK, aliases=("cfg",)),
        CommandSpec(
            "options",
            "options [show] | options set <name> <value> [local|global]",
            "show or set runtime options (persisted; scope in DM only)",
            "General",
            _cmd_options,
            AUTH_MIXED,
            aliases=("opts",),
        ),
        CommandSpec(
            "unlock",
            "unlock [gh|all] [status|ttl] | unlock extend [gh|all] <ttl>",
            "unlock command scopes for your account (status is open; extend requires totp)",
            "Security",
            _cmd_unlock,
            AUTH_TOTP,
            aliases=("ul",),
        ),
        CommandSpec(
            "lock",
            "lock [gh|all] | lock status [gh|all] | lock extend [gh|all] <ttl>",
            "clear unlocks, show unlock status, or extend unlock window",
            "Security",
            _cmd_lock,
            AUTH_MIXED,
            aliases=("lk",),
        ),
        CommandSpec("start", "start [session]", "start a new Codex session", "Sessions", _cmd_start, AUTH_UNLOCK, aliases=("run",)),
        CommandSpec("resume", "resume [session] <prompt>", "resume with prompt", "Sessions", _cmd_resume, AUTH_UNLOCK, aliases=("rs",)),
        CommandSpec(
            "choose",
            "choose [session] continue|new|compact",
            "resolve session conflict prompt",
            "Sessions",
            _cmd_choose,
            AUTH_UNLOCK,
            aliases=("pick",),
        ),
        CommandSpec("use", "use <session>", "set your sticky session", "Sessions", _cmd_use, AUTH_UNLOCK, aliases=("select",)),
        CommandSpec("agent", "agent [session] <backend>", "set session agent backend", "Sessions", _cmd_agent, AUTH_UNLOCK),
        CommandSpec("model", "model [session] <id> [reasoning]", "set session model", "Sessions", _cmd_model, AUTH_UNLOCK, aliases=("mdl",)),
        CommandSpec(
            "models",
            "models [session] [refresh|--refresh]",
            "list available models (cache-first; refresh to re-query Codex)",
            "Sessions",
            _cmd_models,
            AUTH_OPEN,
            aliases=("mdls",),
        ),
        CommandSpec("thread", "thread [session] <id>", "set thread id", "Sessions", _cmd_thread, AUTH_UNLOCK, aliases=("tid",)),
        CommandSpec("reset", "reset [session]", "reset session context", "Sessions", _cmd_reset, AUTH_UNLOCK),
        CommandSpec(
            "workflow",
            "workflow [session] <inspect|fix|review|ship> [focus] | workflow list",
            "run a built-in repo workflow macro",
            "Sessions",
            _cmd_workflow,
            AUTH_UNLOCK,
            aliases=("wf",),
        ),
        CommandSpec("purge", "purge [session] | purge stale <ttl>", "reset session and purge session artifacts", "Sessions", _cmd_purge, AUTH_UNLOCK),
        CommandSpec(
            "session",
            "session status | session prune <ttl> | session archive [session] | session restore [session] [archive-id]",
            "session lifecycle controls",
            "Sessions",
            _cmd_session_lifecycle,
            AUTH_UNLOCK,
            aliases=("sess",),
        ),
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
        CommandSpec("stop", "stop [session]", "send ESC then SIGINT", "Run control", _cmd_stop, AUTH_UNLOCK, aliases=("pause",)),
        CommandSpec(
            "interrupt",
            "interrupt [session]",
            "send ESC interrupt",
            "Run control",
            _cmd_interrupt,
            AUTH_UNLOCK,
            aliases=("int", "esc", "escape"),
        ),
        CommandSpec("kill", "kill [session]", "force kill running process", "Run control", _cmd_kill, AUTH_UNLOCK),
        CommandSpec("/quit", "/quit [session]", "send /quit to Codex", "Run control", _cmd_quit, AUTH_UNLOCK),
        CommandSpec(
            "steer",
            "steer [session] -- <text> | steer <text>",
            "send steering text to active Codex session",
            "Run control",
            _cmd_steer,
            AUTH_UNLOCK,
        ),
        CommandSpec(
            "answer",
            "answer [session] -- <text> | answer <text>",
            "send input to active Codex session",
            "Run control",
            _cmd_answer,
            AUTH_UNLOCK,
            aliases=("reply",),
        ),
        CommandSpec("approve", "approve [session]", "send 'yes' to active session", "Run control", _cmd_approve, AUTH_UNLOCK, aliases=("y",)),
        CommandSpec("deny", "deny [session]", "send 'no' to active session", "Run control", _cmd_deny, AUTH_UNLOCK, aliases=("n",)),
        CommandSpec("wait", "wait", "show sessions awaiting input", "Run control", _cmd_wait, AUTH_UNLOCK, aliases=("w",)),
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
        CommandSpec("branch", "branch", "show current git branch and working tree status", "Repo helpers", _cmd_branch, AUTH_OPEN),
        CommandSpec(
            "git",
            "git <status|log|branches|branch|show|diff|remote|fetch|pull|add|commit|push|merge>",
            "git helpers",
            "Repo helpers",
            _cmd_git,
            AUTH_UNLOCK,
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
        CommandSpec(
            "audit",
            "audit [session] [n] | audit find <term> [n] | audit show <seq> | audit bundle <seq>",
            "audit lookup, filter, and artifact bundle",
            "Queue",
            _cmd_audit,
            AUTH_UNLOCK,
        ),
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


def command_surface(spec: CommandSpec) -> str:
    """Return the redesign surface classification for a command."""
    return COMMAND_MODEL_META.get(spec.name, {}).get("surface", SURFACE_ADVANCED)


def command_namespace(spec: CommandSpec) -> str:
    """Return the redesign namespace/family for a command."""
    return COMMAND_MODEL_META.get(spec.name, {}).get("namespace", "general")


def render_help(specs: Sequence[CommandSpec], prefix: str = "!c") -> str:
    """Compatibility wrapper for index help rendering."""
    return help_renderer.render_help_index(specs, prefix)


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


async def _cmd_help(router: Any, message: MessageEvent, sink: ResponseSink, repo_name: str, repo_path: str, rest: str) -> None:
    await router.send_help(message, sink, rest)


async def _cmd_status(router: Any, message: MessageEvent, sink: ResponseSink, repo_name: str, repo_path: str, rest: str) -> None:
    await router.send_status(message, sink, repo_name, repo_path)


async def _cmd_stats(router: Any, message: MessageEvent, sink: ResponseSink, repo_name: str, repo_path: str, rest: str) -> None:
    session = await _resolve_session_name(router, message, sink, rest.strip())
    if not session:
        return
    await router.handle_stats(sink, session)


async def _cmd_budget(router: Any, message: MessageEvent, sink: ResponseSink, repo_name: str, repo_path: str, rest: str) -> None:
    await router.handle_budget(message, sink, rest)


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
    if (rest or "").strip():
        await router.reply_forbidden(
            sink,
            "Unknown `config` subcommand.\n"
            "Use `!cfg` to show effective config.\n"
            "To change runtime options use: `!opts set <key> <value>`",
        )
        return
    await router.reply(sink, router.config_text())


async def _cmd_options(router: Any, message: MessageEvent, sink: ResponseSink, repo_name: str, repo_path: str, rest: str) -> None:
    await router.handle_options(message, sink, rest)


async def _cmd_updates(router: Any, message: MessageEvent, sink: ResponseSink, repo_name: str, repo_path: str, rest: str) -> None:
    await router.handle_updates(sink, repo_path)


async def _cmd_health(router: Any, message: MessageEvent, sink: ResponseSink, repo_name: str, repo_path: str, rest: str) -> None:
    await router.handle_health(sink, repo_path)


async def _cmd_start(router: Any, message: MessageEvent, sink: ResponseSink, repo_name: str, repo_path: str, rest: str) -> None:
    session_name = (rest or "").strip().split()[0] if (rest or "").strip() else ""
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
        await router.reply_forbidden(sink, "Usage: !c choose [session] continue|new|compact")
        return
    session_name = await _resolve_session_name(router, message, sink, sess)
    if not session_name:
        return
    await router.handle_choose(message, sink, repo_name, repo_path, session_name, choice)


async def _cmd_use(router: Any, message: MessageEvent, sink: ResponseSink, repo_name: str, repo_path: str, rest: str) -> None:
    parts = rest.split()
    if not parts:
        await router.reply_forbidden(sink, "Usage: !c use <session>")
        return
    session_name = await _resolve_session_name(router, message, sink, parts[0], default_from_user=False)
    if not session_name:
        return
    await router.handle_select_session(message, sink, session_name)


async def _cmd_model(router: Any, message: MessageEvent, sink: ResponseSink, repo_name: str, repo_path: str, rest: str) -> None:
    if not rest:
        await router.reply_forbidden(sink, "Usage: !c model [session] <model-id> [reasoning]")
        return
    parts = rest.split()
    session_name = _current_session(router, message)
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


async def _cmd_agent(router: Any, message: MessageEvent, sink: ResponseSink, repo_name: str, repo_path: str, rest: str) -> None:
    from ..agents.factory import KNOWN_BACKENDS
    parts = rest.split()
    if not parts:
        await router.reply_forbidden(sink, "Usage: !c agent [session] <backend-name>")
        return
    session_name = _current_session(router, message)
    backend_name = ""
    if len(parts) == 1:
        backend_name = parts[0]
    else:
        session_name = parts[0]
        backend_name = parts[1]
    session_name = await _resolve_session_name(router, message, sink, session_name)
    if not session_name:
        return
    backend_name = backend_name.strip().lower()
    if backend_name not in KNOWN_BACKENDS:
        known = ", ".join(sorted(KNOWN_BACKENDS))
        await router.reply_forbidden(sink, f"Unknown backend {backend_name!r}. Available: {known}.")
        return

    async def apply_backend() -> None:
        result = router.set_session_backend(message.channel_id, session_name, backend_name)
        parts_msg = [f"Backend for session '{session_name}' set to {backend_name!r}."]
        if result.get("cleared_thread"):
            parts_msg.append("Thread id cleared (cross-backend ids cannot resume).")
        if result.get("cleared_model") or result.get("cleared_effort"):
            parts_msg.append("Model and reasoning effort reset to backend defaults.")
        await router.reply(sink, " ".join(parts_msg))
        await router.update_pinned_status(sink, message.author_id, session_name)

    if await router.has_active(message.channel_id):
        async def job() -> None:
            await apply_backend()
        pos, job_id, _ = await router.coordinator.enqueue(message.channel_id, session_name, job)
        await router.reply(sink, f"Queued backend change for session '{session_name}' to {backend_name!r} as {job_id} (pos {pos}).")
        return

    await apply_backend()


async def _cmd_models(router: Any, message: MessageEvent, sink: ResponseSink, repo_name: str, repo_path: str, rest: str) -> None:
    parts = rest.split()
    refresh_tokens = {"refresh", "--refresh", "-r"}
    refresh = any(p.lower() in refresh_tokens for p in parts)
    parts = [p for p in parts if p.lower() not in refresh_tokens]
    session_name = _current_session(router, message) or DEFAULT_SESSION
    if parts:
        session_name = parts[0]
    session_name = await _resolve_session_name(router, message, sink, session_name, default_from_user=False)
    if not session_name:
        return

    channel_id = message.channel_id
    backend = router.backend_for(channel_id, session_name)

    from ..agents.claude import ClaudeBackend
    from ..agents.gemini import GeminiBackend

    if isinstance(backend, ClaudeBackend):
        models = [
            "claude-opus-4-8      (alias: opus)",
            "claude-sonnet-4-6    (alias: sonnet)",
            "claude-haiku-4-5-20251001 (alias: haiku)",
        ]
        await router.reply(sink, "Available Claude models:\n" + "\n".join(f"- {m}" for m in models))
        return

    if isinstance(backend, GeminiBackend):
        models = [
            "gemini-2.5-pro",
            "gemini-2.5-flash",
            "gemini-3-flash-preview",
        ]
        await router.reply(sink, "Available Gemini models:\n" + "\n".join(f"- {m}" for m in models))
        return

    cached = _read_models_cache()
    if cached and not refresh:
        lines = [f"Available models ({len(cached)}) [cache]:"] + [f"- {m}" for m in cached]
        await router.reply(sink, "\n".join(lines))
        return

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
        args = backend.build_resume_args(repo_path, thread_id, prompt, model, reasoning)
    else:
        # If the session exists but thread id is missing, prefer resume --last to avoid creating a new session.
        if session_exists(state, channel_id, session_name):
            args = backend.build_resume_last_args(repo_path, prompt, model, reasoning)
        else:
            args = backend.build_start_args(repo_path, prompt, model, reasoning)

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
            backend=backend,
        )
        models = parse_models_from_lines(collected)
        if cached and not models:
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


async def _cmd_purge(router: Any, message: MessageEvent, sink: ResponseSink, repo_name: str, repo_path: str, rest: str) -> None:
    _ = (repo_name, repo_path)
    raw = (rest or "").strip()
    parts = raw.split()
    if parts and parts[0].lower() == "stale":
        if len(parts) != 2:
            await router.reply_forbidden(sink, "Usage: !c purge stale <ttl>")
            return
        ttl = _parse_ttl_seconds(parts[1])
        if ttl <= 0:
            await router.reply_forbidden(sink, "TTL must be positive (examples: 30m, 4h, 7d).")
            return
        await router.handle_purge_stale_sessions(message, sink, ttl)
        return
    session = await _resolve_session_name(router, message, sink, raw)
    if not session:
        return
    await router.handle_purge_session(sink, message.channel_id, session)


async def _cmd_session_lifecycle(
    router: Any,
    message: MessageEvent,
    sink: ResponseSink,
    repo_name: str,
    repo_path: str,
    rest: str,
) -> None:
    parts = (rest or "").strip().split()
    if not parts:
        await router.reply_forbidden(
            sink,
            "Usage: !c session status | !c session prune <ttl> | !c session archive [session] | !c session restore [session] [archive-id]",
        )
        return
    action = parts[0].lower()
    if action == "status":
        await router.handle_session_lifecycle_status(message, sink)
        return
    if action == "prune":
        if len(parts) != 2:
            await router.reply_forbidden(sink, "Usage: !c session prune <ttl>")
            return
        ttl = _parse_ttl_seconds(parts[1])
        if ttl <= 0:
            await router.reply_forbidden(sink, "TTL must be positive (examples: 30m, 4h, 7d).")
            return
        await router.handle_session_lifecycle_prune(message, sink, ttl)
        return
    if action == "archive":
        session_name = parts[1] if len(parts) >= 2 else ""
        session_name = await _resolve_session_name(router, message, sink, session_name)
        if not session_name:
            return
        await router.handle_session_lifecycle_archive(message, sink, session_name, repo_name, repo_path)
        return
    if action == "restore":
        if len(parts) > 3:
            await router.reply_forbidden(sink, "Usage: !c session restore [session] [archive-id]")
            return
        session_name = ""
        archive_id = ""
        if len(parts) >= 2:
            session_name = parts[1]
        if len(parts) == 3:
            archive_id = parts[2]
        session_name = await _resolve_session_name(router, message, sink, session_name)
        if not session_name:
            return
        await router.handle_session_lifecycle_restore(message, sink, session_name, repo_name, repo_path, archive_id)
        return
    await router.reply_forbidden(
        sink,
        "Usage: !c session status | !c session prune <ttl> | !c session archive [session] | !c session restore [session] [archive-id]",
    )


def _parse_ttl_seconds(raw: str) -> int:
    token = (raw or "").strip().lower()
    m = _TTL_RE.match(token)
    if not m:
        return 0
    amount = int(m.group(1))
    unit = m.group(2).lower()
    mult = {"m": 60, "h": 3600, "d": 86400}[unit]
    return amount * mult


async def _cmd_spec(router: Any, message: MessageEvent, sink: ResponseSink, repo_name: str, repo_path: str, rest: str) -> None:
    session = await _resolve_session_name(router, message, sink, rest.strip())
    if not session:
        return
    await router.handle_spec(message, sink, repo_name, repo_path, session)


async def _cmd_workflow(router: Any, message: MessageEvent, sink: ResponseSink, repo_name: str, repo_path: str, rest: str) -> None:
    session_token, workflow, focus = _parse_workflow_request(rest)
    if not workflow:
        await router.reply_forbidden(
            sink,
            "Usage: !c workflow [session] <inspect|fix|review|ship> [focus] | !c workflow list",
        )
        return
    if workflow == "list":
        await router.reply(sink, _render_workflow_listing(router._transport_prefix(message)))
        return
    session = await _resolve_session_name(router, message, sink, session_token)
    if not session:
        return
    prompt = _build_workflow_prompt(workflow, repo_name, focus)
    await router.handle_resume(message, sink, repo_name, repo_path, session, prompt)


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
    else:
        session = _current_session(router, message)
    await router.handle_stop(sink, session)


async def _cmd_kill(router: Any, message: MessageEvent, sink: ResponseSink, repo_name: str, repo_path: str, rest: str) -> None:
    session = rest.strip()
    if session:
        session = await _normalize_session_or_reply(router, sink, session)
        if not session:
            return
    else:
        session = _current_session(router, message)
    await router.handle_kill(sink, session)


async def _cmd_interrupt(router: Any, message: MessageEvent, sink: ResponseSink, repo_name: str, repo_path: str, rest: str) -> None:
    session = rest.strip()
    if session:
        session = await _normalize_session_or_reply(router, sink, session)
        if not session:
            return
    else:
        session = _current_session(router, message)
    await router.handle_interrupt(sink, session)


async def _cmd_quit(router: Any, message: MessageEvent, sink: ResponseSink, repo_name: str, repo_path: str, rest: str) -> None:
    session = rest.strip()
    if session:
        session = await _normalize_session_or_reply(router, sink, session)
        if not session:
            return
    else:
        session = _current_session(router, message)
    await router.handle_quit(sink, session)


async def _parse_session_text_args(
    router: Any,
    message: MessageEvent,
    sink: ResponseSink,
    rest: str,
    usage: str,
    empty_message: str,
) -> tuple[str, str] | None:
    rest = (rest or "").strip()
    if not rest:
        await router.reply_forbidden(sink, usage)
        return None
    session = _current_session(router, message)
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
        await router.reply_forbidden(sink, empty_message)
        return None
    return session, text.strip()


async def _cmd_answer(router: Any, message: MessageEvent, sink: ResponseSink, repo_name: str, repo_path: str, rest: str) -> None:
    parsed = await _parse_session_text_args(
        router,
        message,
        sink,
        rest,
        "Usage: !c answer [session] -- <text>  or  !c answer <text>",
        "Answer text required.",
    )
    if not parsed:
        return
    session, text = parsed
    await router.handle_answer(message, sink, session, text)


async def _cmd_steer(router: Any, message: MessageEvent, sink: ResponseSink, repo_name: str, repo_path: str, rest: str) -> None:
    parsed = await _parse_steer_args(router, message, sink, rest)
    if not parsed:
        return
    session, text = parsed
    await router.handle_steer(message, sink, session, text)


async def _parse_steer_args(router: Any, message: MessageEvent, sink: ResponseSink, rest: str) -> tuple[str, str] | None:
    rest = (rest or "").strip()
    usage = "Usage: !c steer [session] -- <text>  or  !c steer <text>"
    if not rest:
        await router.reply_forbidden(sink, usage)
        return None

    explicit_session = ""
    text = rest
    if "--" in rest:
        left, right = rest.split("--", 1)
        text = right.strip()
        left = left.strip()
        if left:
            resolved = await _normalize_session_or_reply(router, sink, left)
            if not resolved:
                return None
            explicit_session = resolved
    if not text.strip():
        await router.reply_forbidden(sink, "Cannot steer: text is required.\n" + usage)
        return None

    if explicit_session:
        return explicit_session, text.strip()

    active_sessions = await router.active_sessions(message.channel_id)
    if not active_sessions:
        await router.reply_forbidden(
            sink,
            "Cannot steer: no active session in this channel. Use `!c start` or `!c resume` first.",
        )
        return None
    if len(active_sessions) > 1:
        await router.reply_forbidden(
            sink,
            "Cannot steer: multiple active sessions (" + ", ".join(active_sessions) + "). Use `!s:<session> <text>`.",
        )
        return None
    return active_sessions[0], text.strip()


async def _cmd_approve(router: Any, message: MessageEvent, sink: ResponseSink, repo_name: str, repo_path: str, rest: str) -> None:
    session = rest.strip()
    if session:
        session = await _normalize_session_or_reply(router, sink, session)
        if not session:
            return
    else:
        session = _current_session(router, message)
    await router.handle_answer(message, sink, session, "yes")


async def _cmd_deny(router: Any, message: MessageEvent, sink: ResponseSink, repo_name: str, repo_path: str, rest: str) -> None:
    session = rest.strip()
    if session:
        session = await _normalize_session_or_reply(router, sink, session)
        if not session:
            return
    else:
        session = _current_session(router, message)
    await router.handle_answer(message, sink, session, "no")


async def _cmd_wait(router: Any, message: MessageEvent, sink: ResponseSink, repo_name: str, repo_path: str, rest: str) -> None:
    await router.handle_wait(message, sink)


async def _cmd_showrepo(router: Any, message: MessageEvent, sink: ResponseSink, repo_name: str, repo_path: str, rest: str) -> None:
    await router.handle_showrepo(sink, repo_path)


async def _cmd_showchanges(router: Any, message: MessageEvent, sink: ResponseSink, repo_name: str, repo_path: str, rest: str) -> None:
    await router.handle_showchanges(sink, repo_path)


async def _cmd_tests(router: Any, message: MessageEvent, sink: ResponseSink, repo_name: str, repo_path: str, rest: str) -> None:
    await router.handle_tests(sink, repo_path)


async def _cmd_branch(router: Any, message: MessageEvent, sink: ResponseSink, repo_name: str, repo_path: str, rest: str) -> None:
    if (rest or "").strip():
        await router.reply_forbidden(sink, "Usage: !c branch")
        return
    await router.handle_branch(sink, repo_path)


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


async def _cmd_audit(router: Any, message: MessageEvent, sink: ResponseSink, repo_name: str, repo_path: str, rest: str) -> None:
    parts = (rest or "").strip().split()
    if parts and parts[0].lower() in {"show", "bundle"}:
        if len(parts) != 2:
            await router.reply_forbidden(sink, f"Usage: !c audit {parts[0].lower()} <seq>")
            return
        if parts[0].lower() == "show":
            await router.handle_audit_show(sink, parts[1])
            return
        await router.handle_audit_bundle(sink, parts[1])
        return
    if parts and parts[0].lower() == "find":
        if len(parts) < 2:
            await router.reply_forbidden(sink, "Usage: !c audit find <term> [n]")
            return
        term = parts[1]
        limit = 10
        if len(parts) >= 3:
            try:
                limit = int(parts[2])
            except ValueError:
                await router.reply_forbidden(sink, "Limit must be an integer.")
                return
        await router.handle_audit_find(sink, term, limit)
        return
    session_name, limit = parse_session_or_limit(rest)
    limit = limit or 10
    if session_name:
        session_name = await _normalize_session_or_reply(router, sink, session_name)
        if not session_name:
            return
    await router.handle_audit_list(sink, session_name, limit)


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
