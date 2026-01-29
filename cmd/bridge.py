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
from codebridge.queue import Manager
from codebridge.router import Router
from codebridge.state import Store


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Discord ↔ Codex CLI Bridge (Python)")
    parser.add_argument("-config", dest="config", default="config.yaml", help="path to config file")
    parser.add_argument("-env", dest="env", default="", help="path to .env file (optional)")
    return parser.parse_args()


async def main() -> None:
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
    audit_logger = AuditLogger(cfg.state.log_dir)
    runner = Runner(cfg.codex.binary, cfg.codex.sandbox, cfg.codex.env)
    queue = Manager()
    router = Router(cfg, state_store, audit_logger, runner, queue, logger)

    token = cfg.discord_token()
    client = build_client(router)

    await client.start(token)


if __name__ == "__main__":
    asyncio.run(main())

