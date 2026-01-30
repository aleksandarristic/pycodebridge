"""CLI entrypoint for the Discord ↔ Codex CLI bridge."""

import argparse
import asyncio
import os
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
    runner = Runner(cfg.codex.binary, cfg.codex.sandbox, cfg.codex.env)
    coordinator = SessionCoordinator(state_store, cfg)
    router = Router(cfg, state_store, audit_logger, runner, coordinator, logger)

    adapter = (cfg.transport.adapter or "discord").lower()
    if adapter == "discord":
        token = cfg.discord_token()
        client = build_client(router)
    elif adapter == "slack":
        raise ValueError("Slack adapter scaffolded but not yet wired; use transport.adapter: discord")
    elif adapter == "telegram":
        token = cfg.telegram_token()
        app = build_application(router, token)
        await run_polling(app, router)
        return
    else:
        raise ValueError(f"Unsupported transport adapter: {adapter}")

    try:
        await client.start(token)
    except asyncio.CancelledError:
        logger.info("shutdown", extra={"reason": "cancelled"})
        await client.close()
    except KeyboardInterrupt:
        logger.info("shutdown", extra={"reason": "keyboard_interrupt"})
        await client.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
