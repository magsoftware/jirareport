from __future__ import annotations

import sys
from typing import Any

from loguru import logger

MAX_LOC_LENGTH = 40


def configure_logging(debug: bool) -> None:
    """Configures Loguru with a compact location-aware format.

    Args:
        debug: Whether debug-level logging should be enabled.
    """
    logger.remove()
    level = "DEBUG" if debug else "INFO"
    logger.add(
        sys.stderr,
        level=level,
        enqueue=True,
        backtrace=False,
        diagnose=False,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level:<8}</level> | "
            "<cyan>{extra[location]}</cyan> - <level>{message}</level>"
        ),
        filter=_format_location,
    )
    logger.info("Logging initialized with custom format and location handler")


def _format_location(record: Any) -> bool:
    """Formats the ``location`` field used by the log output template.

    Args:
        record: Mutable Loguru record payload.

    Returns:
        Always ``True`` so the record is emitted after enrichment.
    """
    location = f"{record['name']}:{record['function']}:{record['line']}"
    if len(location) > MAX_LOC_LENGTH:
        location = location[-MAX_LOC_LENGTH:]
    else:
        location = location.ljust(MAX_LOC_LENGTH)
    record["extra"]["location"] = location
    return True
