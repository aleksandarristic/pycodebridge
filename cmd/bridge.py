"""CLI entrypoint for the Discord ↔ Codex CLI bridge."""

import argparse
import asyncio
import os
import signal
from contextlib import suppress
from pathlib import Path

from dotenv import load_dotenv

from codebridge import config as cfgmod
from codebridge import logging as logmod
from codebridge.audit import Logger as AuditLogger
from codebridge.codex import Runner
from codebridge.discord_bot import build_client
from codebridge.telegram_bot import build_application, run_polling
from codebridge.router import Router
from codebridge.session_coordinator import SessionCoordinator
from codebridge.state import Store


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
        from codebridge.audit import Redactor

        redactor = Redactor(cfg.audit.redact_patterns)
    audit_logger = AuditLogger(cfg.state.log_dir, redactor=redactor)
    runner = Runner(
        cfg.codex.binary,
        cfg.codex.sandbox,
        cfg.codex.env,
        cfg.codex.ask_for_approval,
        cfg.codex.network_access,
    )
    coordinator = SessionCoordinator(state_store, cfg)
    router = Router(cfg, state_store, audit_logger, runner, coordinator, logger)

    adapter = (cfg.transport.adapter or "discord").lower()
    if adapter == "discord":
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
    elif adapter == "slack":
        raise ValueError("Slack adapter scaffolded but not yet wired; use transport.adapter: discord")
    elif adapter == "telegram":
        token = cfg.telegram_token()
        app = build_application(router, token)
        await run_polling(app, router)
        return
    else:
        raise ValueError(f"Unsupported transport adapter: {adapter}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
