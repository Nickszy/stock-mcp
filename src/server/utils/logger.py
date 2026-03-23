# src/server/utils/logger.py
"""Structured logging configuration using structlog.
All modules should import logger via:
    from src.server.utils.logger import logger
"""
import logging
import os
import sys
from logging.handlers import RotatingFileHandler

import structlog


def configure_logging(level: str = "INFO"):
    handlers = [logging.StreamHandler(sys.stderr)]

    log_file = os.getenv("LOG_FILE")
    if log_file:
        log_dir = os.path.dirname(log_file)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
            print(f"[log] created log directory: {log_dir}", file=sys.stderr)
        print(f"[log] writing to file: {log_file}", file=sys.stderr)
        handlers.append(
            RotatingFileHandler(
                log_file,
                maxBytes=50 * 1024 * 1024,
                backupCount=5,
                encoding="utf-8",
            )
        )

    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=handlers,
    )

    # 使用 ConsoleRenderer 输出更易读的格式
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S"),
            structlog.processors.add_log_level,
            # 移除多余的字段
            structlog.processors.StackInfoRenderer(),
            # 使用 ConsoleRenderer 输出彩色、易读的格式
            structlog.dev.ConsoleRenderer(colors=True, exception_formatter=structlog.dev.plain_traceback),
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )


# Initialize at import time
configure_logging()
logger = structlog.get_logger()
