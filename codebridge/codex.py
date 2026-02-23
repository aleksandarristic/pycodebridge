"""Codex CLI runner and JSONL parsing utilities."""

import asyncio
import json
import os
import signal
import subprocess
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Optional

from .util.ansi import strip_control_codes
from .util.prompt import needs_user_input


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


def extract_thread_id(line: str) -> str:
    """Extract thread_id from a JSONL line if present."""
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        return ""
    return payload.get("thread_id") or payload.get("threadId") or ""


def agent_texts(evt: Event) -> list[str]:
    """Extract agent-visible text blocks from an Event."""
    texts: list[str] = []
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


def display_texts(evt: Event) -> list[str]:
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


@dataclass
class Options:
    """Options for running a Codex command."""
    repo_path: str
    args: list[str]
    env: Dict[str, str]
    on_jsonl: Optional[Callable[[str], Awaitable[None]]] = None
    on_thread: Optional[Callable[[str], Awaitable[None]]] = None
    on_output: Optional[Callable[[str], Awaitable[None]]] = None
    on_stderr: Optional[Callable[[str], Awaitable[None]]] = None
    on_exit: Optional[Callable[[Optional[BaseException], int], Awaitable[None]]] = None


class Process:
    """Handle to a running Codex process."""
    def __init__(self, proc: asyncio.subprocess.Process) -> None:
        self._proc = proc
        self._thread_id = ""

    @property
    def thread_id(self) -> str:
        """Thread id captured from the Codex JSONL stream."""
        return self._thread_id

    def set_thread_id(self, thread_id: str) -> None:
        """Set thread id once, ignoring subsequent updates."""
        if not self._thread_id:
            self._thread_id = thread_id

    async def stop(self) -> None:
        """Send ESC to request a graceful stop."""
        if self._proc.stdin:
            self._proc.stdin.write(b"\x1b")
            await self._proc.stdin.drain()

    async def interrupt(self) -> None:
        """Send an interrupt signal (SIGINT/CTRL_BREAK)."""
        if self._proc.returncode is None:
            if os.name == "nt":
                if hasattr(signal, "CTRL_BREAK_EVENT"):
                    self._proc.send_signal(signal.CTRL_BREAK_EVENT)
                else:
                    self._proc.send_signal(signal.SIGTERM)
            else:
                self._proc.send_signal(signal.SIGINT)

    async def kill(self) -> None:
        """Force-kill the process."""
        if self._proc.returncode is None:
            self._proc.kill()

    async def write(self, text: str) -> None:
        """Write raw text to Codex stdin."""
        if self._proc.stdin:
            self._proc.stdin.write(text.encode("utf-8"))
            await self._proc.stdin.drain()

    async def wait(self) -> int:
        """Wait for process exit and return returncode."""
        return await self._proc.wait()


class Runner:
    """Build and execute Codex CLI commands."""
    def __init__(
        self,
        binary: str,
        sandbox: str,
        base_env: Optional[Dict[str, str]] = None,
        ask_for_approval: str = "",
        network_access: bool = False,
    ) -> None:
        self.binary = binary or "codex"
        self.sandbox = sandbox or "workspace-write"
        self.base_env = base_env or {}
        self.ask_for_approval = (ask_for_approval or "").strip()
        self.network_access = bool(network_access)

    def _base_exec_args(self, repo_path: str) -> list[str]:
        args: list[str] = ["exec", "--json", "--cd", repo_path]
        if self.sandbox:
            args += ["--sandbox", self.sandbox]
        if self.ask_for_approval:
            args += ["-c", f"approval_policy={_toml_string(self.ask_for_approval)}"]
        if self.network_access and self.sandbox == "workspace-write":
            args += ["-c", "sandbox_workspace_write.network_access=true"]
        return args

    def build_start_args(self, repo_path: str, prompt: str, model: str, reasoning_effort: str) -> list[str]:
        """Build args for starting a new Codex session."""
        args = self._base_exec_args(repo_path)
        if model.strip():
            args += ["--model", model]
        args += _reasoning_args(reasoning_effort)
        args.append(prompt)
        return args

    def build_resume_args(self, repo_path: str, thread_id: str, prompt: str, model: str, reasoning_effort: str) -> list[str]:
        """Build args for resuming a session by thread id."""
        args = self._base_exec_args(repo_path) + ["resume", thread_id]
        if model.strip():
            args += ["--model", model]
        args += _reasoning_args(reasoning_effort)
        args.append(prompt)
        return args

    def build_resume_last_args(self, repo_path: str, prompt: str, model: str, reasoning_effort: str) -> list[str]:
        """Build args for resuming the last session in a repo."""
        args = self._base_exec_args(repo_path) + ["resume", "--last"]
        if model.strip():
            args += ["--model", model]
        args += _reasoning_args(reasoning_effort)
        args.append(prompt)
        return args

    async def run(self, opts: Options) -> Process:
        """Run Codex with given options and stream JSONL output to callbacks."""
        if not opts.repo_path:
            raise ValueError("repo path required")
        if not opts.args:
            raise ValueError("args required")

        env = _merge_env(self.base_env, opts.env)
        creationflags = 0
        if os.name == "nt":
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
        proc = await asyncio.create_subprocess_exec(
            self.binary,
            *opts.args,
            cwd=opts.repo_path,
            env=env,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            creationflags=creationflags,
        )
        process = Process(proc)

        async def _read_stdout() -> Optional[BaseException]:
            """Read stdout JSONL and forward to callbacks."""
            assert proc.stdout
            try:
                async for raw in proc.stdout:
                    line = raw.decode("utf-8", errors="replace").rstrip("\n")
                    if opts.on_jsonl:
                        await opts.on_jsonl(line)
                    thread_id = extract_thread_id(line)
                    if thread_id:
                        process.set_thread_id(thread_id)
                        if opts.on_thread:
                            await opts.on_thread(thread_id)
                    evt = parse_event(line)
                    if evt:
                        for text in display_texts(evt):
                            clean = strip_control_codes(text)
                            if needs_user_input(clean):
                                clean = f"Codex asks: {clean}"
                            if opts.on_output:
                                await opts.on_output(clean)
                return None
            except Exception as exc:
                return exc

        async def _read_stderr() -> Optional[BaseException]:
            """Read stderr and forward to callback if provided."""
            if not proc.stderr:
                return None
            try:
                async for raw in proc.stderr:
                    line = raw.decode("utf-8", errors="replace").rstrip("\n")
                    if opts.on_stderr:
                        await opts.on_stderr(line)
                return None
            except Exception as exc:
                return exc

        stdout_task = asyncio.create_task(_read_stdout())
        stderr_task = asyncio.create_task(_read_stderr())

        async def _waiter() -> None:
            """Wait for process completion and invoke on_exit callback."""
            err = await stdout_task
            stderr_err = await stderr_task
            rc = await proc.wait()
            if err is None and stderr_err is not None:
                err = stderr_err
            if opts.on_exit:
                await opts.on_exit(err, rc)

        asyncio.create_task(_waiter())
        return process


def _merge_env(base: Dict[str, str], extra: Dict[str, str]) -> Dict[str, str]:
    """Merge environment variables using an allowlist baseline."""
    env = {}
    allow = {
        "PATH",
        "HOME",
        "USER",
        "SHELL",
        "TMPDIR",
        "TEMP",
        "TMP",
        "LANG",
        "LC_ALL",
        "TERM",
        "COLORTERM",
        "SSH_AUTH_SOCK",
        "SSH_AGENT_PID",
        "GOCACHE",
        "GOMODCACHE",
        "GOPATH",
        "XDG_CACHE_HOME",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
        "GH_CONFIG_DIR",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "NO_PROXY",
        "ALL_PROXY",
        "GH_TOKEN",
        "GITHUB_TOKEN",
    }
    for name in allow:
        if name in os.environ:
            env[name] = os.environ[name]
    env.update(base or {})
    env.update(extra or {})
    return env


def _toml_string(value: str) -> str:
    """Return a TOML-safe quoted string for --config overrides."""
    return json.dumps(value or "")


def _reasoning_args(reasoning_effort: str) -> list[str]:
    effort = (reasoning_effort or "").strip()
    if not effort:
        return []
    return ["-c", f"model_reasoning_effort={_toml_string(effort)}"]
