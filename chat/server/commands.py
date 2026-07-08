"""Server command handlers."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

Handler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


class CommandRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, Handler] = {}

    def command(self, name: str) -> Callable[[Handler], Handler]:
        def decorator(func: Handler) -> Handler:
            self._handlers[name] = func
            return func
        return decorator

    async def run(self, name: str, payload: dict[str, Any]) -> dict[str, Any]:
        if name not in self._handlers:
            return {"ok": False, "error": f"unknown command: {name}"}
        return await self._handlers[name](payload)


registry = CommandRegistry()
