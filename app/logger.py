"""Logging configuration for ICL Reliability Engine."""
import logging
import os
from pathlib import Path

from config.config import Config


def setup_logging():
    """Configure logging to file and console."""
    log_dir = Path(Config.LOG_DIR)
    log_dir.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logger = logging.getLogger("icl_engine")

    # File handler for app status
    try:
        file_handler = logging.FileHandler(Config.APP_STATUS_PATH, encoding="utf-8")
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
        )
        logger.addHandler(file_handler)
    except (OSError, PermissionError):
        pass

    return logger


def log_status(message: str, level: str = "info"):
    """Log status to app_status.log."""
    logger = logging.getLogger("icl_engine")
    getattr(logger, level)(message)
