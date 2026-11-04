"""structlog setup: JSON when `LOG_FORMAT=json`, readable console output otherwise."""

from __future__ import annotations

import logging
import sys

import structlog


def configure_logging(log_format: str = "console") -> None:
    renderer: structlog.types.Processor = (
        structlog.processors.JSONRenderer() if log_format == "json" else structlog.dev.ConsoleRenderer()
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=False,
    )
