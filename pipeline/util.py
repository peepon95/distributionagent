"""Small shared helpers: retry-with-backoff, slugs, duration parsing."""

from __future__ import annotations

import logging
import re
import time
from typing import Callable, TypeVar

T = TypeVar("T")

logger = logging.getLogger(__name__)

_ISO8601_DURATION = re.compile(
    r"^P(?:(?P<days>\d+)D)?"
    r"(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)?$"
)


def with_retries(
    fn: Callable[[], T],
    *,
    attempts: int = 4,
    base_delay: float = 1.0,
    retry_on: tuple[type[Exception], ...] = (Exception,),
) -> T:
    """Call fn, retrying with exponential backoff on transient errors."""
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except retry_on as exc:
            if attempt == attempts:
                raise
            delay = base_delay * (2 ** (attempt - 1))
            logger.warning(
                "Attempt %d/%d failed (%s: %s); retrying in %.1fs",
                attempt, attempts, type(exc).__name__, exc, delay,
            )
            time.sleep(delay)
    raise AssertionError("unreachable")


def slugify(text: str) -> str:
    """Lowercase, replace non-alphanumerics with underscores, trim."""
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return slug or "untitled"


def iso8601_duration_to_seconds(duration: str) -> int:
    """Convert a YouTube ISO 8601 duration (e.g. 'PT1H2M30S') to seconds."""
    match = _ISO8601_DURATION.match(duration)
    if not match:
        raise ValueError(f"Unparseable ISO 8601 duration: {duration!r}")
    parts = {k: int(v) for k, v in match.groupdict().items() if v}
    return (
        parts.get("days", 0) * 86400
        + parts.get("hours", 0) * 3600
        + parts.get("minutes", 0) * 60
        + parts.get("seconds", 0)
    )
