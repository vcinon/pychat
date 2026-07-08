"""Linux desktop notifications."""

from __future__ import annotations

import asyncio
import shutil


class Notifier:
    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled and shutil.which("notify-send") is not None

    async def message(self, title: str, body: str) -> None:
        if not self.enabled:
            return
        proc = await asyncio.create_subprocess_exec("notify-send", title, body)
        await proc.communicate()
