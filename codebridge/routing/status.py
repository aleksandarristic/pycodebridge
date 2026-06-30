"""Helper utilities for formatting router status output."""

from __future__ import annotations


from ..sessions.state import SessionState


def format_session_line(
    name: str,
    session: SessionState,
    active: bool,
    backend: str,
    model: str,
    reasoning: str,
    show_reasoning: bool = True,
) -> str:
    """Format a single session entry for status output."""
    active_flag = " (active)" if active else ""
    backend_info = f" agent {backend}" if backend else ""
    model_info = f" model {model}" if model else ""
    reasoning_info = f" reasoning {reasoning}" if show_reasoning and reasoning else ""
    return f"- {name}:{backend_info} thread {session.thread_id}{active_flag}{model_info}{reasoning_info} last {session.last_used_at}"


def format_current_selection_line(
    session_name: str,
    backend: str,
    model: str,
    reasoning: str,
    show_reasoning: bool = True,
) -> str:
    """Format the current sticky session selection line for status output."""
    backend_info = f" agent {backend}" if backend else ""
    model_info = f" model {model}" if model else ""
    reasoning_info = f" reasoning {reasoning}" if show_reasoning and reasoning else ""
    return f"Current selection: {session_name}{backend_info}{model_info}{reasoning_info}"
