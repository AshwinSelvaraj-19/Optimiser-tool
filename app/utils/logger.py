"""
Structured logging system for Phoenix Optimizer.
Logs to file and console with rotation and structured format.
"""

import logging
import logging.handlers
import os
import sys
from datetime import datetime
from pathlib import Path

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)-30s | %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_logger_initialized = False
_app_logger = None


def setup_logging(log_dir: str | None = None, level: int = logging.DEBUG) -> logging.Logger:
    """Initialize the logging system with file and console handlers."""
    global _logger_initialized, _app_logger

    if _logger_initialized and _app_logger is not None:
        return _app_logger

    if log_dir is None:
        log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
    os.makedirs(log_dir, exist_ok=True)

    log_file = os.path.join(log_dir, f"phoenix_{datetime.now().strftime('%Y%m%d')}.log")

    root_logger = logging.getLogger("phoenix")
    root_logger.setLevel(level)
    root_logger.handlers.clear()

    # File handler with rotation (10MB max, keep 5 backups)
    file_handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(logging.Formatter(LOG_FORMAT, LOG_DATE_FORMAT))

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter(LOG_FORMAT, LOG_DATE_FORMAT))

    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    _app_logger = root_logger
    _logger_initialized = True

    root_logger.info("=" * 60)
    root_logger.info("Heaven Society v1.0.0")
    root_logger.info("Logging system initialized")
    root_logger.info(f"Log file: {log_file}")
    root_logger.info("=" * 60)

    return root_logger


def get_logger(name: str) -> logging.Logger:
    """Get a child logger with the given name."""
    if not _logger_initialized:
        setup_logging()
    return logging.getLogger(f"phoenix.{name}")


class LogContext:
    """Context manager for structured logging of operations."""

    def __init__(self, logger: logging.Logger, operation: str, level: int = logging.INFO):
        self.logger = logger
        self.operation = operation
        self.level = level

    def __enter__(self):
        self.logger.log(self.level, f"START: {self.operation}")
        self._start_time = datetime.now()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        duration = (datetime.now() - self._start_time).total_seconds()
        if exc_type is None:
            self.logger.log(self.level, f"COMPLETE: {self.operation} ({duration:.2f}s)")
        else:
            self.logger.error(f"FAILED: {self.operation} ({duration:.2f}s) - {exc_val}")
        return False  # Don't suppress exceptions
