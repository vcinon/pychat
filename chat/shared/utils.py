"""Shared utility helpers."""

from __future__ import annotations

import asyncio
import logging
import signal
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path


def utc_now() -> datetime:
    return datetime.now(UTC)


def iso_now() -> str:
    return utc_now().isoformat()


def parse_size(value: str) -> int:
    units = {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3}
    text = value.strip().upper()
    for unit, multiplier in sorted(units.items(), key=lambda item: len(item[0]), reverse=True):
        if text.endswith(unit):
            return int(float(text[: -len(unit)].strip()) * multiplier)
    return int(text)


def ensure_dir(path: str | Path) -> Path:
    directory = Path(path)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def configure_logging(name: str, level: str = "INFO") -> logging.Logger:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    return logging.getLogger(name)


def install_signal_handlers(stop: asyncio.Event, logger: logging.Logger) -> None:
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda s=sig: (logger.info("received %s", s.name), stop.set()))
        except NotImplementedError:
            pass


async def suppress_cancelled(coro_factory: Callable[[], Awaitable[None]]) -> None:
    try:
        await coro_factory()
    except asyncio.CancelledError:
        raise
    except Exception:  # pragma: no cover - defensive task guard
        logging.getLogger(__name__).exception("background task failed")
