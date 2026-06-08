"""Codex CLI backend: argument building and JSONL parsing.

The backend-agnostic subprocess runner, ``Options`` contract, ``Process``
handle, and ``NormalizedEvent`` seam live in :mod:`codebridge.agents.base`.
This module keeps only Codex-specific concerns and adapts them to the
:class:`~codebridge.agents.base.AgentBackend` interface.
"""

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .agents.base import AgentBackend, NormalizedEvent, Options, Process

__all__ = [
    "Event",
    "parse_event",
    "agent_texts",
    "display_texts",
    "CodexBackend",
    "Runner",
    "Options",
    "Process",
    "NormalizedEvent",
]


@dataclass
class Event:
    """Parsed Codex JSONL event wrapper."""
    type: str
    thread_id: str = ""
    item: Optional[Dict[str, Any]] = None
    content: str = ""
    text: str = ""
    message: str = ""
    error: Optional[Dict[str, Any]] = None
    usage: Optional[Dict[str, Any]] = None


def parse_event(line: str) -> Optional[Event]:
    """Parse a JSONL line into an Event, or return None on error."""
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        return None
    return Event(
        type=payload.get("type", ""),
        thread_id=payload.get("thread_id", "") or payload.get("threadId", ""),
        item=payload.get("item"),
        content=payload.get("content", ""),
        text=payload.get("text", ""),
        message=payload.get("message", ""),
        error=payload.get("error"),
        usage=payload.get("usage"),
    )


def agent_texts(evt: Event) -> List[str]:
    """Extract agent-visible text blocks from an Event."""
    texts: List[str] = []
    if evt.item:
        item_type = evt.item.get("type", "")
        if _is_agent_like(item_type):
            text = evt.item.get("text")
            if text:
                texts.append(text)
            for c in evt.item.get("content", []) or []:
                if not isinstance(c, dict):
                    continue
                c_text = c.get("text")
                c_type = c.get("type", "")
                if c_text and (_is_agent_like(c_type) or c_type in {"text", "output_text"}):
                    texts.append(c_text)
    if not texts and evt.text:
        texts.append(evt.text)
    if not texts and evt.content:
        texts.append(evt.content)
    return texts


def display_texts(evt: Event) -> List[str]:
    """Return displayable texts from an Event, falling back to error messages."""
    texts = agent_texts(evt)
    if texts:
        return texts
    if evt.message:
        texts.append(_normalize_message(evt.message))
    if evt.error:
        msg = evt.error.get("message") or ""
        detail = evt.error.get("detail") or ""
        if msg:
            texts.append(_normalize_message(msg))
        if detail:
            texts.append(detail)
    return [t for t in texts if t]


def _normalize_message(msg: str) -> str:
    """Normalize structured error messages into plain text."""
    msg = (msg or "").strip()
    if msg.startswith("{") and "detail" in msg:
        try:
            payload = json.loads(msg)
            return payload.get("detail") or payload.get("error") or msg
        except json.JSONDecodeError:
            return msg
    return msg


def _is_agent_like(t: str) -> bool:
    """Return True for agent-like item types."""
    if not t:
        return True
    return t in {"agent_message", "message", "output_text"}


class CodexBackend(AgentBackend):
    """Build and execute Codex CLI commands."""

    ask_prefix = "Codex asks:"

    def __init__(
        self,
        binary: str,
        sandbox: str,
        base_env: Optional[Dict[str, str]] = None,
        ask_for_approval: str = "",
        network_access: bool = False,
    ) -> None:
        super().__init__(binary or "codex", base_env)
        self.sandbox = sandbox or "workspace-write"
        self.ask_for_approval = (ask_for_approval or "").strip()
        self.network_access = bool(network_access)

    def _base_exec_args(self, repo_path: str) -> List[str]:
        args: List[str] = ["exec", "--json", "--cd", repo_path]
        if self.sandbox:
            args += ["--sandbox", self.sandbox]
        if self.ask_for_approval:
            args += ["-c", f"approval_policy={_toml_string(self.ask_for_approval)}"]
        if self.network_access and self.sandbox == "workspace-write":
            args += ["-c", "sandbox_workspace_write.network_access=true"]
        return args

    def build_start_args(self, repo_path: str, prompt: str, model: str, reasoning_effort: str) -> List[str]:
        """Build args for starting a new Codex session."""
        args = self._base_exec_args(repo_path)
        if model.strip():
            args += ["--model", model]
        args += _reasoning_args(reasoning_effort)
        args.append(prompt)
        return args

    def build_resume_args(self, repo_path: str, thread_id: str, prompt: str, model: str, reasoning_effort: str) -> List[str]:
        """Build args for resuming a session by thread id."""
        args = self._base_exec_args(repo_path) + ["resume", thread_id]
        if model.strip():
            args += ["--model", model]
        args += _reasoning_args(reasoning_effort)
        args.append(prompt)
        return args

    def build_resume_last_args(self, repo_path: str, prompt: str, model: str, reasoning_effort: str) -> List[str]:
        """Build args for resuming the last session in a repo."""
        args = self._base_exec_args(repo_path) + ["resume", "--last"]
        if model.strip():
            args += ["--model", model]
        args += _reasoning_args(reasoning_effort)
        args.append(prompt)
        return args

    def parse(self, line: str) -> Optional[NormalizedEvent]:
        """Parse a Codex JSONL line into a backend-neutral event."""
        evt = parse_event(line)
        if evt is None:
            return None
        return NormalizedEvent(
            type=evt.type,
            session_id=evt.thread_id,
            texts=display_texts(evt),
            usage=evt.usage,
            error=evt.error,
            raw=line,
        )


# Backward-compatible alias: the Codex backend was historically the only runner.
Runner = CodexBackend


def _toml_string(value: str) -> str:
    """Return a TOML-safe quoted string for --config overrides."""
    s = value or ""
    if not s.isascii():
        raise ValueError(f"non-ASCII characters are not supported in config values: {s!r}")
    return json.dumps(s)


def _reasoning_args(reasoning_effort: str) -> List[str]:
    effort = (reasoning_effort or "").strip()
    if not effort:
        return []
    return ["-c", f"model_reasoning_effort={_toml_string(effort)}"]
