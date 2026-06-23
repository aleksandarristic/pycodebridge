"""CLI entrypoint for the Discord ↔ Codex CLI bridge."""

import argparse
import asyncio
import os
import signal
from contextlib import suppress
from pathlib import Path

from dotenv import load_dotenv

from codebridge import config as cfgmod
from codebridge.observability import logging as logmod
from codebridge.observability.audit import Logger as AuditLogger
from codebridge.agents import build_backend
from codebridge.platform.discord_bot import build_client
from codebridge.services.health import start_health_server
from codebridge.services.worktree import WorktreeManager
from codebridge.dispatch.orchestrator import Orchestrator
from codebridge.dispatch.closer import TaskCloser
from codebridge.routing.router import Router
from codebridge.sessions.coordinator import SessionCoordinator
from codebridge.sessions.state import Store


def _install_signal_handlers(stop_event: asyncio.Event) -> None:
    """Install SIGINT/SIGTERM handlers that trigger graceful shutdown."""
    loop = asyncio.get_running_loop()
    for name in ("SIGINT", "SIGTERM"):
        sig = getattr(signal, name, None)
        if sig is None:
            continue
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            # add_signal_handler is not available on all platforms/event loops.
            continue


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(description="Discord ↔ Codex CLI Bridge (Python)")
    parser.add_argument("-config", dest="config", default="config.yaml", help="path to config file")
    parser.add_argument("-env", dest="env", default="", help="path to .env file (optional)")
    return parser.parse_args()


async def main() -> None:
    """Main async entrypoint for running the Discord client."""
    args = parse_args()
    config_path = args.config
    env_path = args.env

    if not env_path:
        env_path = str(Path(config_path).resolve().parent / ".env")
    if os.path.exists(env_path):
        load_dotenv(env_path)

    cfg = cfgmod.load(config_path)
    logger = logmod.setup_logging(cfg.runtime.log_level, cfg.state.log_dir)

    state_store = Store(cfg.state.data_dir, cfg.state.lock_timeout_seconds)
    redactor = None
    if cfg.audit.redact:
        from codebridge.observability.audit import Redactor

        redactor = Redactor(cfg.audit.redact_patterns)
    audit_logger = AuditLogger(cfg.state.log_dir, redactor=redactor)
    runner = build_backend(cfg)
    coordinator = SessionCoordinator(state_store, cfg)
    wt_manager: WorktreeManager | None = None
    if cfg.worktrees.enabled:
        wt_manager = WorktreeManager(
            base_dir=cfg.worktrees.base_dir,
            max_per_repo=cfg.worktrees.max_per_repo,
            cleanup_on_end=cfg.worktrees.cleanup_on_end,
        )
        code_root = cfg.codex.code_root
        if code_root and os.path.isdir(code_root):
            for entry in os.scandir(code_root):
                if entry.is_dir() and os.path.isdir(os.path.join(entry.path, ".git")):
                    await wt_manager.prune_stale(entry.path)
    orchestrator: Orchestrator | None = None
    task_closer: TaskCloser | None = None
    if wt_manager is not None:
        orchestrator = Orchestrator(cfg, wt_manager, coordinator)
        task_closer = TaskCloser(cfg, coordinator)
    router = Router(cfg, state_store, audit_logger, runner, coordinator, logger, wt_manager=wt_manager, orchestrator=orchestrator, task_closer=task_closer)
    await router.bootstrap_git_config()
    health_server = None
    if (cfg.runtime.health_bind or "").strip():
        health_server = await start_health_server(
            router,
            logger,
            cfg.runtime.health_bind,
            cfg.runtime.health_path,
            allow_public=cfg.runtime.health_allow_public,
        )

    adapter = (cfg.transport.adapter or "discord").lower()
    try:
        if adapter != "discord":
            raise ValueError(f"Unsupported transport adapter: {adapter} (discord only)")
        token = cfg.discord_token()
        client = build_client(router)
        stop_event = asyncio.Event()
        _install_signal_handlers(stop_event)

        client_task = asyncio.create_task(client.start(token))
        stop_task = asyncio.create_task(stop_event.wait())

        done, _ = await asyncio.wait({client_task, stop_task}, return_when=asyncio.FIRST_COMPLETED)
        if stop_task in done and not client_task.done():
            logger.info("shutdown", extra={"reason": "signal"})
            await client.close()
            try:
                await asyncio.wait_for(client_task, timeout=10)
            except asyncio.TimeoutError:
                client_task.cancel()
                with suppress(asyncio.CancelledError):
                    await client_task
        else:
            with suppress(asyncio.CancelledError):
                await client_task
        stop_task.cancel()
        return
    finally:
        if health_server is not None:
            health_server.close()
            await health_server.wait_closed()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
