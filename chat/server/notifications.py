"""Server notification hooks."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def notify_event(event: str, detail: str) -> None:
    logger.info("%s: %s", event, detail)
