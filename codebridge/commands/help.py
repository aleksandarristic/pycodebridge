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
    "status": ("!st",),
    "updates": ("!u",),
    "health": ("!health", "!diag"),
    "wait": ("!w",),
    "ps": ("!ps",),
    "rerun": ("!retry",),
    "approve": ("!y",),
    "deny": ("!n",),
    "interrupt": ("!stop [session]", "!pause [session]"),
    "steer": ("!steer <text>", "!s <text>", "!s:<session> <text>"),
    "answer": ("!a <text>", "!a:<session> <text>"),
    "git": ("!git ...",),
    "gh": ("!gh ...",),
    "logs": ("!log [n]",),
    "unlock": ("!unlock ...", "!ul ..."),
    "lock": ("!lock ...",),
    "help": ("!help",),
    "config": ("!cfg",),
    "options": ("!options", "!opts"),
}

COMMAND_DETAILS = {
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
}


def render_help_index(specs: Sequence[object], prefix: str = "!c") -> str:
    """Render grouped command index."""
    grouped = _group_specs(specs)
    lines = [
        "Commands:",
        "Auth tags: [open]=no TOTP, [unlock/default]=default unlock or --totp, [unlock/gh]=gh unlock or --totp, [totp]=always --totp, [mixed]=depends on subcommand",
        "",
    ]
    for group in _ordered_groups(grouped):
        lines.append(f"{group}:")
        for spec in grouped[group]:
            auth_text = AUTH_LABELS.get(spec.auth, spec.auth)
            triggers = ", ".join(f"**`{trig}`**" for trig in help_triggers(spec, prefix))
            lines.append(f"- {triggers} - {spec.description} [{auth_text}]")
        lines.append("")
    return "\n".join(lines).strip()


def render_help_command(spec: object, prefix: str = "!c") -> str:
    """Render detailed help for a single command."""
    auth_text = AUTH_LABELS.get(spec.auth, spec.auth)
    detail = COMMAND_DETAILS.get(spec.name, {})
    lines = [
        f"**Help: `{spec.name}`**",
        f"Triggers: {', '.join(f'**`{t}`**' for t in help_triggers(spec, prefix))}",
        f"Auth: `[{auth_text}]`",
        f"Description: {spec.description}",
    ]
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


def default_examples(spec: object, prefix: str) -> tuple[str, ...]:
    head = f"{prefix} {spec.name}".strip()
    if " " in spec.usage:
        return (f"{head}",)
    return (head,)


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
