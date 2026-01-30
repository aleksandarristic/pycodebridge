"""Helper utilities for formatting router status output."""

from __future__ import annotations

from dataclasses import dataclass

from .state import SessionState


def format_session_line(
    name: str,
    session: SessionState,
    active: bool,
    default_model: str,
    default_reasoning: str,
) -> str:
    """Format a single session entry for status output."""
    model = session.model or default_model
    reasoning = session.reasoning_effort or default_reasoning
    active_flag = " (active)" if active else ""
    model_info = f" model {model}" if model else ""
    reasoning_info = f" reasoning {reasoning}" if reasoning else ""
    return f"- {name}: thread {session.thread_id}{active_flag}{model_info}{reasoning_info} last {session.last_used_at}"


def format_current_selection_line(session_name: str, model: str, reasoning: str) -> str:
    """Format the current sticky session selection line for status output."""
    model_info = f" model {model}" if model else ""
    reasoning_info = f" reasoning {reasoning}" if reasoning else ""
    return f"Current selection: {session_name}{model_info}{reasoning_info}"
