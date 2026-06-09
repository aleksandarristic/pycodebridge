"""Construct agent backends by name from config.

Per-session backend selection (TASK-0070) resolves a backend name to an
instance through :func:`build_backend`. For now only the Codex backend is
registered; additional backends register here as they land.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .base import AgentBackend

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .. import config as cfgmod

DEFAULT_BACKEND = "codex"
KNOWN_BACKENDS: frozenset[str] = frozenset({"codex"})


def build_backend(cfg: "cfgmod.Config", name: str = DEFAULT_BACKEND) -> AgentBackend:
    """Return an :class:`AgentBackend` for ``name`` built from ``cfg``."""
    backend = (name or DEFAULT_BACKEND).strip().lower()
    if backend == "codex":
        from ..codex import CodexBackend

        return CodexBackend(
            cfg.codex.binary,
            cfg.codex.sandbox,
            cfg.codex.env,
            cfg.codex.ask_for_approval,
            cfg.codex.network_access,
        )
    raise ValueError(f"unknown agent backend: {name!r}")
