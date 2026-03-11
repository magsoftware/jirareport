from __future__ import annotations

import sys

from loguru import logger


def configure_logging(debug: bool) -> None:
    """Configures loguru for CLI and GitHub Actions execution."""
    logger.remove()
    level = "DEBUG" if debug else "INFO"
    logger.add(
        sys.stdout,
        level=level,
        enqueue=True,
        backtrace=False,
        diagnose=False,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
    )
