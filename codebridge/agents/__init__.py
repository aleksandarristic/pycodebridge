"""Agent backend abstraction.

``base`` holds the backend-agnostic subprocess runner plus the
``AgentBackend`` interface and the ``NormalizedEvent`` seam used by routing
and session code. Concrete backends (e.g. Codex) live in their own modules and
are constructed via :func:`build_backend`.
"""

from .base import AgentBackend, NormalizedEvent, Options, Process
from .factory import build_backend

__all__ = [
    "AgentBackend",
    "NormalizedEvent",
    "Options",
    "Process",
    "build_backend",
]
