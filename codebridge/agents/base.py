"""Backend-agnostic agent runner and interface.

This module owns everything that does not depend on a specific agent CLI:
the subprocess plumbing (:class:`Process`, :func:`AgentBackend.run`), the
:class:`Options` callback contract, the env allowlist, and the
:class:`NormalizedEvent` that backends emit so routing/session code never
parses CLI-specific JSONL itself.

Concrete backends subclass :class:`AgentBackend` and implement the
argument-building and :meth:`AgentBackend.parse` methods; the streaming
``run`` loop is shared.
"""

import asyncio
import os
import signal
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional

try:
    import pty
except ImportError:  # pragma: no cover - Windows fallback.
    pty = None  # type: ignore[assignment]

from ..util.ansi import strip_control_codes
from ..util.prompt import needs_user_input

_background_tasks: set[asyncio.Task[Any]] = set()


@dataclass
class NormalizedEvent:
    """Backend-neutral view of one streamed event.

    Backends translate their native JSONL into this shape so consumers
    (router, usage accounting) depend only on these fields, not on any
    particular CLI's schema.
    """
    type: str = ""
    session_id: str = ""
    texts: List[str] = field(default_factory=list)
    usage: Optional[Dict[str, Any]] = None
    error: Optional[Dict[str, Any]] = None
    raw: str = ""


@dataclass
class Options:
    """Options for running an agent command."""
    repo_path: str
    args: List[str]
    env: Dict[str, str]
    on_jsonl: Optional[Callable[[str, Optional[NormalizedEvent]], Awaitable[None]]] = None
    on_thread: Optional[Callable[[str], Awaitable[None]]] = None
    on_output: Optional[Callable[[str], Awaitable[None]]] = None
    on_stderr: Optional[Callable[[str], Awaitable[None]]] = None
    on_exit: Optional[Callable[[Optional[BaseException], int], Awaitable[None]]] = None


class Process:
    """Handle to a running agent process."""
    def __init__(self, proc: asyncio.subprocess.Process, stdin_fd: Optional[int] = None) -> None:
        self._proc = proc
        self._stdin_fd = stdin_fd
        self._thread_id = ""

    @property
    def thread_id(self) -> str:
        """Session/thread id captured from the agent stream."""
        return self._thread_id

    def set_thread_id(self, thread_id: str) -> None:
        """Set thread id once, ignoring subsequent updates."""
        if not self._thread_id:
            self._thread_id = thread_id

    async def stop(self) -> None:
        """Send ESC to request a graceful stop."""
        await self._write_bytes(b"\x1b")

    def interrupt(self) -> None:
        """Send an interrupt signal (SIGINT/CTRL_BREAK)."""
        if self._proc.returncode is None:
            if os.name == "nt":
                if hasattr(signal, "CTRL_BREAK_EVENT"):
                    self._proc.send_signal(signal.CTRL_BREAK_EVENT)
                else:
                    self._proc.send_signal(signal.SIGTERM)
            else:
                self._proc.send_signal(signal.SIGINT)

    def kill(self) -> None:
        """Force-kill the process."""
        if self._proc.returncode is None:
            self._proc.kill()

    async def write(self, text: str) -> None:
        """Write raw text to the agent stdin."""
        await self._write_bytes(text.encode("utf-8"))

    async def wait(self) -> int:
        """Wait for process exit and return returncode."""
        try:
            return await self._proc.wait()
        finally:
            self.close_stdin()

    async def _write_bytes(self, data: bytes) -> None:
        if self._stdin_fd is not None:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, os.write, self._stdin_fd, data)
            return
        if self._proc.stdin:
            self._proc.stdin.write(data)
            await self._proc.stdin.drain()

    def close_stdin(self) -> None:
        """Close the parent-side stdin handle, if any."""
        if self._stdin_fd is not None:
            try:
                os.close(self._stdin_fd)
            except OSError:
                pass
            self._stdin_fd = None


class AgentBackend(ABC):
    """Common interface and shared runner for agent CLIs.

    Subclasses provide CLI argument construction and :meth:`parse`; the
    streaming ``run`` loop, env handling, and process lifecycle are shared.
    """

    #: Prefix applied to output that appears to be a request for user input.
    ask_prefix: str = "Agent asks:"

    def __init__(self, binary: str, base_env: Optional[Dict[str, str]] = None) -> None:
        self.binary = binary
        self.base_env = base_env or {}

    @abstractmethod
    def build_start_args(self, repo_path: str, prompt: str, model: str, reasoning_effort: str) -> List[str]:
        """Build args for starting a new session."""

    @abstractmethod
    def build_resume_args(self, repo_path: str, thread_id: str, prompt: str, model: str, reasoning_effort: str) -> List[str]:
        """Build args for resuming a session by id."""

    @abstractmethod
    def build_resume_last_args(self, repo_path: str, prompt: str, model: str, reasoning_effort: str) -> List[str]:
        """Build args for resuming the last session in a repo."""

    @abstractmethod
    def parse(self, line: str) -> Optional[NormalizedEvent]:
        """Parse a single JSONL line into a :class:`NormalizedEvent`."""

    async def run(self, opts: Options) -> Process:
        """Run the backend with given options and stream events to callbacks."""
        if not opts.repo_path:
            raise ValueError("repo path required")
        if not opts.args:
            raise ValueError("args required")

        env = _merge_env(self.base_env, opts.env)
        creationflags = 0
        if os.name == "nt":
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
        stdin = asyncio.subprocess.PIPE
        stdin_fd: Optional[int] = None
        stdin_slave_fd: Optional[int] = None
        if os.name != "nt" and pty is not None:
            stdin_fd, stdin_slave_fd = pty.openpty()
            stdin = stdin_slave_fd
        try:
            proc = await asyncio.create_subprocess_exec(
                self.binary,
                *opts.args,
                cwd=opts.repo_path,
                env=env,
                stdin=stdin,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                creationflags=creationflags,
            )
        finally:
            if stdin_slave_fd is not None:
                try:
                    os.close(stdin_slave_fd)
                except OSError:
                    pass
        process = Process(proc, stdin_fd)

        async def _read_stdout() -> Optional[BaseException]:
            """Read stdout JSONL and forward to callbacks."""
            if not proc.stdout:
                return RuntimeError("agent process has no stdout")
            try:
                async for raw in proc.stdout:
                    line = raw.decode("utf-8", errors="replace").rstrip("\n")
                    # Parse once; the parsed event is reused by every consumer
                    # below (on_jsonl, thread-id capture, on_output).
                    evt = self.parse(line)
                    if opts.on_jsonl:
                        await opts.on_jsonl(line, evt)
                    thread_id = evt.session_id if evt else ""
                    if thread_id:
                        process.set_thread_id(thread_id)
                        if opts.on_thread:
                            await opts.on_thread(thread_id)
                    if opts.on_output and evt:
                        for text in evt.texts:
                            clean = strip_control_codes(text)
                            if needs_user_input(clean):
                                clean = f"{self.ask_prefix} {clean}"
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

        _task = asyncio.create_task(_waiter())
        _background_tasks.add(_task)
        _task.add_done_callback(_background_tasks.discard)
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
