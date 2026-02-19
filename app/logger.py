"""Logging configuration for Predictive Maintenance Engine.

Log format: [TIMESTAMP] [LEVEL] [MODULE] - Message.
"""
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from config.config import Config

LOG_FORMAT = "[%(asctime)s] [%(levelname)s] [%(name)s] - %(message)s"
LOG_DATEFMT = "%Y-%m-%d %H:%M:%S"
# Rotation: max 10 MB per file, 3 backups (app_status.log.1, .2, .3)
LOG_MAX_BYTES = 10 * 1024 * 1024
LOG_BACKUP_COUNT = 3


def setup_logging() -> logging.Logger:
    """Configure logging to console and rotating app_status.log.

    Returns:
        Logger named "pump_engine".
    """
    log_dir = Path(Config.LOG_DIR)
    log_dir.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format=LOG_FORMAT,
        datefmt=LOG_DATEFMT,
    )
    logger = logging.getLogger("pump_engine")

    try:
        file_handler = RotatingFileHandler(
            Config.APP_STATUS_PATH,
            maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=LOG_DATEFMT))
        logger.addHandler(file_handler)
    except (OSError, PermissionError):
        pass

    return logger


def log_status(message: str, level: str = "info") -> None:
    """Write message to app_status.log at the given level.

    Args:
        message: Log message text.
        level: Log level: "info", "warning", "error", "debug".
    """
    logger = logging.getLogger("pump_engine")
    getattr(logger, level)(message)
