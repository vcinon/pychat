"""Extensible client command framework."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol


class ClientLike(Protocol):
    async def request_history(self, limit: int = 100) -> None: ...
    async def send_file(self, path: str) -> None: ...
    async def ping_once(self) -> None: ...
    async def stop(self) -> None: ...
    def show(self, message: str) -> None: ...

Handler = Callable[[ClientLike, list[str]], Awaitable[None]]


@dataclass(frozen=True)
class Command:
    name: str
    help: str
    handler: Handler


class Registry:
    def __init__(self) -> None:
        self.commands: dict[str, Command] = {}

    def register(self, name: str, help: str) -> Callable[[Handler], Handler]:
        def decorator(func: Handler) -> Handler:
            self.commands[name] = Command(name, help, func)
            return func
        return decorator

    async def execute(self, client: ClientLike, line: str) -> bool:
        parts = line.split()
        name = parts[0][1:]
        command = self.commands.get(name)
        if command is None:
            client.show(f"Unknown command: /{name}")
            return True
        await command.handler(client, parts[1:])
        return True


registry = Registry()


@registry.register("help", "Show commands")
async def help_cmd(client: ClientLike, args: list[str]) -> None:
    client.show("Commands: " + ", ".join(f"/{c.name}" for c in registry.commands.values()))

@registry.register("ping", "Measure latency")
async def ping_cmd(client: ClientLike, args: list[str]) -> None: await client.ping_once()
@registry.register("uptime", "Show server uptime")
async def uptime_cmd(client: ClientLike, args: list[str]) -> None: client.show("Uptime is tracked by the server logs.")
@registry.register("send", "Send a file")
async def send_cmd(client: ClientLike, args: list[str]) -> None: await client.send_file(" ".join(args)) if args else client.show("Usage: /send FILE")
@registry.register("history", "Load history")
async def history_cmd(client: ClientLike, args: list[str]) -> None: await client.request_history(int(args[0]) if args else 100)
@registry.register("clear", "Clear screen")
async def clear_cmd(client: ClientLike, args: list[str]) -> None: client.show("Clear by restarting the live view.")
@registry.register("online", "Show online users")
async def online_cmd(client: ClientLike, args: list[str]) -> None: client.show("Presence is displayed in the header.")
@registry.register("status", "Show status")
async def status_cmd(client: ClientLike, args: list[str]) -> None: client.show("Client running.")
@registry.register("version", "Show version")
async def version_cmd(client: ClientLike, args: list[str]) -> None:
    from chat.shared.constants import VERSION
    client.show(VERSION)
@registry.register("quit", "Quit")
async def quit_cmd(client: ClientLike, args: list[str]) -> None: await client.stop()
