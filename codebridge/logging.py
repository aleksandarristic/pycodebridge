import logging
import os
from logging.handlers import RotatingFileHandler


def setup_logging(level: str, log_dir: str) -> logging.Logger:
    logger = logging.getLogger("pycodebridge")
    if logger.handlers:
        return logger

    level_name = (level or "info").lower()
    level_value = {
        "debug": logging.DEBUG,
        "info": logging.INFO,
        "warn": logging.WARNING,
        "warning": logging.WARNING,
        "error": logging.ERROR,
    }.get(level_name, logging.INFO)

    logger.setLevel(level_value)
    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%SZ",
    )

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    logger.addHandler(console)

    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, "bridge.log")
        file_handler = RotatingFileHandler(log_path, maxBytes=5 * 1024 * 1024, backupCount=3)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger

