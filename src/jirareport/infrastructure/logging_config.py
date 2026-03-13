from __future__ import annotations

import sys
from typing import TYPE_CHECKING, cast

from loguru import logger

if TYPE_CHECKING:
    from loguru import Record

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


def flush_logging() -> None:
    """Waits until all queued log messages are written to configured sinks."""
    logger.complete()


def _format_location(record: Record) -> bool:
    """Formats the ``location`` field used by the log output template.

    Args:
        record: Mutable Loguru record payload.

    Returns:
        Always ``True`` so the record is emitted after enrichment.
    """
    name = record["name"] or ""
    location = f"{name}:{record['function']}:{record['line']}"
    if len(location) > MAX_LOC_LENGTH:
        location = location[-MAX_LOC_LENGTH:]
    else:
        location = location.ljust(MAX_LOC_LENGTH)
    extra = cast(dict[str, object], record["extra"])
    extra["location"] = location
    return True
