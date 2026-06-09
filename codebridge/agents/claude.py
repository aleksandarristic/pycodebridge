"""Claude Code CLI backend.

Implements :class:`AgentBackend` for `claude -p --output-format stream-json`.
Stream-json schema documented in .task-management/TASK-0071-claude-stream-json-schema.md.
"""

import json
from typing import Dict, List, Optional

from .base import AgentBackend, NormalizedEvent

_PERMISSION_MODES = frozenset({"default", "acceptEdits", "auto", "bypassPermissions"})

# Auth env vars that Claude Code needs in headless / Docker contexts.
CLAUDE_AUTH_ENV_VARS = frozenset({
    "ANTHROPIC_API_KEY",
    "CLAUDE_CODE_OAUTH_TOKEN",
    "CLAUDE_CONFIG_DIR",
})


class ClaudeBackend(AgentBackend):
    """Build and execute Claude Code CLI (`claude -p`) commands."""

    ask_prefix = "Claude asks:"

    def __init__(
        self,
        binary: str,
        permission_mode: str = "default",
        base_env: Optional[Dict[str, str]] = None,
        model: str = "",
        effort: str = "",
    ) -> None:
        super().__init__(binary or "claude", base_env)
        self.permission_mode = permission_mode or "default"
        self.default_model = model or ""
        self.default_effort = effort or ""

    def _base_args(self, repo_path: str, model: str, effort: str) -> List[str]:
        args = [
            "-p",
            "--output-format", "stream-json",
            "--verbose",
            "--add-dir", repo_path,
        ]
        effective_model = model.strip() or self.default_model
        if effective_model:
            args += ["--model", effective_model]
        effective_effort = effort.strip() or self.default_effort
        if effective_effort:
            args += ["--effort", effective_effort]
        if self.permission_mode == "bypassPermissions":
            args.append("--dangerously-skip-permissions")
        elif self.permission_mode and self.permission_mode != "default":
            args += ["--permission-mode", self.permission_mode]
        return args

    def build_start_args(self, repo_path: str, prompt: str, model: str, reasoning_effort: str) -> List[str]:
        return self._base_args(repo_path, model, reasoning_effort) + [prompt]

    def build_resume_args(self, repo_path: str, thread_id: str, prompt: str, model: str, reasoning_effort: str) -> List[str]:
        return self._base_args(repo_path, model, reasoning_effort) + ["--resume", thread_id, prompt]

    def build_resume_last_args(self, repo_path: str, prompt: str, model: str, reasoning_effort: str) -> List[str]:
        return self._base_args(repo_path, model, reasoning_effort) + ["--continue", prompt]

    def parse(self, line: str) -> Optional[NormalizedEvent]:
        """Parse one stream-json line into a backend-neutral event."""
        try:
            obj = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            return None

        t = obj.get("type", "")

        if t == "system" and obj.get("subtype") == "init":
            return NormalizedEvent(
                type="init",
                session_id=obj.get("session_id", ""),
                raw=line,
            )

        if t == "assistant":
            msg = obj.get("message") or {}
            texts = [
                block["text"]
                for block in msg.get("content", [])
                if isinstance(block, dict) and block.get("type") == "text" and block.get("text")
            ]
            return NormalizedEvent(
                type="message",
                texts=texts,
                raw=line,
            )

        if t == "result":
            is_error = obj.get("is_error", False) or obj.get("subtype") == "error"
            error = None
            if is_error:
                error = {
                    "message": obj.get("result", ""),
                    "subtype": obj.get("subtype", "error"),
                }
            return NormalizedEvent(
                type="result",
                session_id=obj.get("session_id", ""),
                usage=obj.get("usage"),
                error=error,
                raw=line,
            )

        return None
