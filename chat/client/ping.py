"""Latency measurement state."""

from __future__ import annotations

import time


class PingTracker:
    def __init__(self) -> None:
        self.pending: dict[str, float] = {}
        self.last_ms: int | None = None

    def sent(self, packet_id: str) -> None:
        self.pending[packet_id] = time.perf_counter()

    def received(self, packet_id: str) -> int | None:
        started = self.pending.pop(packet_id, None)
        if started is None:
            return None
        self.last_ms = int((time.perf_counter() - started) * 1000)
        return self.last_ms
