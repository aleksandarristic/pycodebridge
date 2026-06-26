"""Gemini CLI backend.

Implements :class:`AgentBackend` for `gemini -p --output-format stream-json`.
Stream-json schema documented in .task-management/TASK-0020-gemini-stream-json-schema.md.
"""

from dataclasses import replace
import json
import os
from typing import Dict, List, Optional

from .base import AgentBackend, NormalizedEvent

_APPROVAL_MODES = frozenset({"default", "auto_edit", "yolo", "plan"})

# Auth env vars that the Gemini CLI needs in headless / Docker contexts.
GEMINI_AUTH_ENV_VARS = frozenset({
    "GEMINI_API_KEY",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "GOOGLE_CLOUD_PROJECT",
    "GEMINI_CLI_TRUST_WORKSPACE",
})


class GeminiBackend(AgentBackend):
    """Build and execute Gemini CLI (`gemini -p`) commands."""

    ask_prefix = "Gemini asks:"

    def __init__(
        self,
        binary: str,
        approval_mode: str = "yolo",
        base_env: Optional[Dict[str, str]] = None,
        model: str = "",
        api_key_env: str = "",
    ) -> None:
        super().__init__(binary or "gemini", base_env)
        self.approval_mode = approval_mode or "yolo"
        self.default_model = model or ""
        self.api_key_env = (api_key_env or "").strip()
        self._last_error_msg: str = ""

    def _base_args(self, model: str) -> List[str]:
        args = ["-o", "stream-json", "--skip-trust"]
        effective_model = model.strip() or self.default_model
        if effective_model:
            args += ["-m", effective_model]
        if self.approval_mode and self.approval_mode != "default":
            args += ["--approval-mode", self.approval_mode]
        return args

    def build_start_args(self, repo_path: str, prompt: str, model: str, reasoning_effort: str) -> List[str]:
        return self._base_args(model) + ["-p", prompt]

    def build_resume_args(self, repo_path: str, thread_id: str, prompt: str, model: str, reasoning_effort: str) -> List[str]:
        return self._base_args(model) + ["--resume", thread_id, "-p", prompt]

    def build_resume_last_args(self, repo_path: str, prompt: str, model: str, reasoning_effort: str) -> List[str]:
        return self._base_args(model) + ["--resume", "latest", "-p", prompt]

    async def run(self, opts):
        if not self.api_key_env:
            return await super().run(opts)
        api_key = os.environ.get(self.api_key_env, "")
        if not api_key:
            raise ValueError(
                f"Gemini API key env var '{self.api_key_env}' is not set. "
                "Set it in the bridge process environment or clear `gemini.api_key_env` to use `gemini.env`/other Gemini auth."
            )
        env = dict(opts.env or {})
        env["GEMINI_API_KEY"] = api_key
        return await super().run(replace(opts, env=env))

    def parse(self, line: str) -> Optional[NormalizedEvent]:
        """Parse one stream-json line into a backend-neutral event."""
        try:
            obj = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            return None

        t = obj.get("type", "")

        if t == "init":
            return NormalizedEvent(
                type="init",
                session_id=obj.get("session_id", ""),
                raw=line,
            )

        if t == "message" and obj.get("role") == "assistant":
            content = obj.get("content", "")
            return NormalizedEvent(
                type="message",
                texts=[content] if content else [],
                raw=line,
            )

        if t == "error":
            # Stash for the result event that follows.
            self._last_error_msg = obj.get("message", "")
            return None

        if t == "result":
            is_error = obj.get("status") == "error"
            error = None
            if is_error:
                result_error = obj.get("error")
                if isinstance(result_error, dict):
                    error_msg = result_error.get("message", "")
                    error_type = result_error.get("type", "error")
                elif isinstance(result_error, str):
                    error_msg = result_error
                    error_type = "error"
                else:
                    error_msg = self._last_error_msg
                    error_type = "error"
                error = {
                    "message": error_msg,
                    "subtype": error_type or "error",
                }
                self._last_error_msg = ""
            return NormalizedEvent(
                type="result",
                usage=obj.get("stats"),
                error=error,
                raw=line,
            )

        return None
