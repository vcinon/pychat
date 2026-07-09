"""Extensible client command framework."""

from __future__ import annotations

import shlex
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class ClientLike(Protocol):
    async def request_history(self, limit: int = 100) -> None: ...
    async def send_file(self, path: str) -> None: ...
    async def ping_once(self) -> None: ...
    async def stop(self) -> None: ...
    async def notify_command(self, name: str) -> None: ...
    def set_command_panel(self, mode: str) -> None: ...
    def change_directory(self, path: str) -> None: ...
    def list_directory(self, path: str | None = None) -> None: ...
    def print_working_directory(self) -> None: ...
    def show(self, message: str) -> None: ...
    def clear_screen(self) -> None: ...

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
        try:
            parts = shlex.split(line)
        except ValueError as exc:
            client.show(f"Invalid command syntax: {exc}")
            return True
        if not parts:
            return True
        name = parts[0][1:]
        command = self.commands.get(name)
        if command is None:
            client.show(f"Unknown command: /{name}")
            return True
        await client.notify_command(name)
        await command.handler(client, parts[1:])
        return True

    def complete(self, line: str) -> str | None:
        if not line.startswith("/"):
            return None
        parts = line.split()
        if len(parts) <= 1 and not line.endswith(" "):
            prefix = line[1:]
            matches = [f"/{name}" for name in self.commands if name.startswith(prefix)]
            if len(matches) == 1:
                return matches[0] + " "
            return None
        command = parts[0][1:]
        if command in {"send", "ls", "cd"}:
            token = "" if line.endswith(" ") else parts[-1]
            raw_path = Path(token).expanduser()
            parent = raw_path.parent if raw_path.parent != Path(".") else Path.cwd()
            pattern = raw_path.name + "*"
            matches = sorted(parent.glob(pattern))
            if len(matches) == 1:
                suffix = "/" if matches[0].is_dir() else " "
                return f"{parts[0]} {matches[0]}{suffix}"
        return None

    def help_items(self) -> list[tuple[str, str]]:
        return [(f"/{command.name}", command.help) for command in self.commands.values()]


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
@registry.register("commands", "Show/hide command panel")
async def commands_cmd(client: ClientLike, args: list[str]) -> None: client.set_command_panel(args[0] if args else "show")
@registry.register("pwd", "Show local working directory")
async def pwd_cmd(client: ClientLike, args: list[str]) -> None: client.print_working_directory()
@registry.register("ls", "List local files")
async def ls_cmd(client: ClientLike, args: list[str]) -> None: client.list_directory(args[0] if args else None)
@registry.register("cd", "Change local working directory")
async def cd_cmd(client: ClientLike, args: list[str]) -> None: client.change_directory(args[0] if args else "~")
@registry.register("history", "Load history")
async def history_cmd(client: ClientLike, args: list[str]) -> None: await client.request_history(int(args[0]) if args else 100)
@registry.register("clear", "Clear screen")
async def clear_cmd(client: ClientLike, args: list[str]) -> None: client.clear_screen()
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
