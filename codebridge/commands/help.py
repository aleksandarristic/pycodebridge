"""Render command help index and per-command details."""

from __future__ import annotations

from difflib import get_close_matches
from typing import Mapping, Sequence


AUTH_LABELS = {
    "open": "open",
    "unlock": "unlock/default",
    "unlock-gh": "unlock/gh",
    "totp": "totp",
    "mixed": "mixed",
}

HELP_SHORTCUT_TRIGGERS = {
    "steer": ("!s <text>", "!s:<session> <text>"),
    "answer": ("!a <text>", "!a:<session> <text>"),
}

PROMOTED_PREFERRED_TRIGGERS = {
    "answer": "!a <text>",
    "steer": "!s <text>",
    "approve": "!y",
    "deny": "!n",
}

NAMESPACE_LABELS = {
    "general": "Orientation",
    "session": "Session lifecycle",
    "run": "Active run control",
    "repo": "Repo inspection",
    "diag": "Diagnostics and queue",
    "admin": "Security and runtime config",
    "repo-admin": "Repo lifecycle",
}

COMMAND_DETAILS = {
    "branch": {
        "details": "Shows the current branch and whether the working tree is clean.",
        "examples": (
            "!c branch",
            "!branch",
        ),
    },
    "git": {
        "details": "Runs safe git helper commands from the mapped repository.",
        "examples": (
            "!c help git",
            "!c git status",
            "!c git add README.md",
            "!c git fetch origin",
            "!c git log 5",
            "!git diff HEAD~1..HEAD",
        ),
    },
    "unlock": {
        "details": "Unlocks TOTP scopes for your account; status is read-only.",
        "examples": (
            "!c unlock 123456 1h",
            "!c unlock gh 123456 1h",
            "!c unlock status",
            "!c unlock extend 30m --totp 123456",
        ),
    },
    "lock": {
        "details": "Clears unlock windows, checks unlock status, or extends an active unlock window.",
        "examples": (
            "!c lock",
            "!c lock status",
            "!c lock extend 30m --totp 123456",
        ),
    },
    "help": {
        "details": "Shows full command index or detailed help for a specific command.",
        "examples": (
            "!c help",
            "!help",
            "!c help git",
            "!c help unlock",
        ),
    },
    "health": {
        "details": "Shows runtime diagnostics including queue/session counts and environment sanity checks.",
        "examples": (
            "!c health",
            "!health",
            "!diag",
        ),
    },
    "options": {
        "details": "Shows or updates runtime options. Changes apply immediately and are persisted; DM can target local or global scope.",
        "examples": (
            "!c options",
            "!options",
            "!c options set run_heartbeat_seconds 120 --totp 123456",
            "!c options set show_reasoning_details false global --totp 123456",
        ),
    },
    "workflow": {
        "details": "Expands a small set of built-in repo workflow macros into standardized Codex prompts.",
        "examples": (
            "!c workflow list",
            "!c workflow inspect auth flow",
            "!c workflow review",
            "!c workflow fix failing tests",
        ),
    },
    "clear": {
        "details": "Clears the channel's default session without resolving the repo or invoking an agent backend.",
        "examples": (
            "!c clear",
            "!clear",
        ),
    },
}


def render_help_index(specs: Sequence[object], prefix: str = "!c") -> str:
    """Render help around the preferred operator workflow."""
    core_specs = [spec for spec in specs if _spec_surface(spec) == "core"]
    support_specs = [spec for spec in specs if _spec_surface(spec) == "support"]
    advanced_specs = [spec for spec in specs if _spec_surface(spec) == "advanced"]
    admin_specs = [spec for spec in specs if _spec_surface(spec) == "admin"]
    lines = [
        "Commands:",
        "Golden path first. Prefer `!c ...` commands for most actions.",
        "Promoted run shortcuts: `!a <text>`, `!s <text>`, `!y`, `!n`.",
        "Other aliases and top-level `!<command>` forms remain supported for compatibility but are not listed first.",
        "",
    ]
    _append_help_section(lines, "Golden path", core_specs, prefix)
    _append_help_section(lines, "Advanced and support", support_specs + advanced_specs, prefix)
    _append_help_section(lines, "Admin and maintenance", admin_specs, prefix)
    return "\n".join(lines).strip()


def render_help_command(spec: object, prefix: str = "!c") -> str:
    """Render detailed help for a single command."""
    auth_text = AUTH_LABELS.get(spec.auth, spec.auth)
    detail = COMMAND_DETAILS.get(spec.name, {})
    preferred = preferred_help_trigger(spec, prefix)
    also_available = [trigger for trigger in help_triggers(spec, prefix) if trigger != preferred]
    lines = [
        f"**Help: `{spec.name}`**",
        f"Preferred: **`{preferred}`**",
    ]
    if also_available:
        lines.append(f"Also available: {', '.join(f'**`{t}`**' for t in also_available)}")
    lines.extend(
        [
        f"Surface: `{_spec_surface(spec)}`",
        f"Namespace: `{_namespace_label(spec)}`",
        f"Auth: `[{auth_text}]`",
        f"Description: {spec.description}",
        ]
    )
    extra = detail.get("details")
    if extra:
        lines.append(f"Details: {extra}")
    lines.append("Examples:")
    examples = detail.get("examples") or default_examples(spec, prefix)
    for ex in examples:
        lines.append(f"- `{ex}`")
    return "\n".join(lines)


def help_not_found(query: str, registry: Mapping[str, object], prefix: str = "!c") -> str:
    """Render unknown-command help guidance."""
    keys = sorted({k for k in registry.keys() if "/" not in k})
    choices = get_close_matches((query or "").strip().lower(), keys, n=5, cutoff=0.45)
    if choices:
        rendered = ", ".join(f"`{prefix} help {name}`" for name in choices)
        return f"Unknown command `{query}`. Try: {rendered}"
    return f"Unknown command `{query}`. Use `{prefix} help` to list commands."


def help_triggers(spec: object, prefix: str = "!c") -> list[str]:
    """Return render-friendly trigger list for one command."""
    pref = (prefix or "!c").strip()
    heads = [spec.name] + list(spec.aliases)
    out: list[str] = []
    forms = [f.strip() for f in spec.usage.split(" | ") if f.strip()]
    for form in forms:
        parts = form.split(maxsplit=1)
        if not parts:
            continue
        head = parts[0]
        tail = f" {parts[1]}" if len(parts) > 1 else ""
        if head == spec.name:
            for alias in heads:
                out.append(f"{pref} {alias}{tail}".strip())
                out.append(f"!{alias}{tail}".strip())
        else:
            out.append(f"{pref} {form}".strip())
    for shortcut in HELP_SHORTCUT_TRIGGERS.get(spec.name, ()):
        out.append(shortcut)
    deduped: list[str] = []
    for trig in out:
        t = trig.strip()
        if t and t not in deduped:
            deduped.append(t)
    return deduped


def preferred_help_trigger(spec: object, prefix: str = "!c") -> str:
    promoted = PROMOTED_PREFERRED_TRIGGERS.get(spec.name)
    if promoted:
        return promoted
    pref = (prefix or "!c").strip()
    forms = [f.strip() for f in spec.usage.split(" | ") if f.strip()]
    if not forms:
        return f"{pref} {spec.name}".strip()
    form = forms[0]
    parts = form.split(maxsplit=1)
    tail = f" {parts[1]}" if len(parts) > 1 else ""
    return f"{pref} {spec.name}{tail}".strip()


def default_examples(spec: object, prefix: str) -> tuple[str, ...]:
    return (preferred_help_trigger(spec, prefix),)


def _group_specs(specs: Sequence[object]) -> dict[str, list[object]]:
    grouped: dict[str, list[object]] = {}
    for spec in specs:
        grouped.setdefault(spec.group, []).append(spec)
    return grouped


def _ordered_groups(grouped: dict[str, list[object]]) -> list[str]:
    order = ("General", "Security", "Sessions", "Repo lifecycle", "Run control", "Repo helpers", "Queue")
    out: list[str] = []
    seen = set()
    for group in order:
        if group in grouped:
            out.append(group)
            seen.add(group)
    for group in grouped.keys():
        if group not in seen:
            out.append(group)
    return out


def _append_help_section(lines: list[str], heading: str, specs: Sequence[object], prefix: str) -> None:
    if not specs:
        return
    lines.append(f"{heading}:")
    grouped = _group_by_namespace(specs)
    for namespace in _ordered_namespaces(grouped):
        lines.append(f"{_namespace_heading(namespace)}:")
        for spec in grouped[namespace]:
            auth_text = AUTH_LABELS.get(spec.auth, spec.auth)
            lines.append(f"- **`{preferred_help_trigger(spec, prefix)}`** - {spec.description} [{auth_text}]")
        lines.append("")


def _group_by_namespace(specs: Sequence[object]) -> dict[str, list[object]]:
    grouped: dict[str, list[object]] = {}
    for spec in specs:
        grouped.setdefault(_spec_namespace(spec), []).append(spec)
    return grouped


def _ordered_namespaces(grouped: dict[str, list[object]]) -> list[str]:
    order = ("general", "session", "run", "repo", "diag", "admin", "repo-admin")
    out: list[str] = []
    seen = set()
    for namespace in order:
        if namespace in grouped:
            out.append(namespace)
            seen.add(namespace)
    for namespace in grouped.keys():
        if namespace not in seen:
            out.append(namespace)
    return out


def _namespace_heading(namespace: str) -> str:
    return NAMESPACE_LABELS.get(namespace, namespace.replace("-", " ").title())


def _namespace_label(spec: object) -> str:
    return _namespace_heading(_spec_namespace(spec))


def _spec_surface(spec: object) -> str:
    from . import registry as command_registry

    return command_registry.command_surface(spec)


def _spec_namespace(spec: object) -> str:
    from . import registry as command_registry

    return command_registry.command_namespace(spec)
