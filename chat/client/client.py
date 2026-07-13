"""Chat client application logic.

This module owns networking, protocol handling, and local state. It knows
nothing about Textual (or any other UI toolkit) -- it only talks to a
``UIPort``, a small protocol describing the operations a presentation layer
must implement. This keeps the UI code (see :mod:`chat.client.ui`) cleanly
separated from the business logic, and makes the client testable without a
terminal.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Protocol

from dotenv import load_dotenv

from chat.client.commands import registry
from chat.client.crypto import MessageCrypto
from chat.client.file_transfer import download, upload
from chat.client.images import is_image_path
from chat.client.notifications import Notifier
from chat.client.ping import PingTracker
from chat.client.websocket import WebSocketClient
from chat.shared.constants import IDLE_TIMEOUT_SECONDS, PING_INTERVAL_SECONDS
from chat.shared.packet import Packet, PacketType
from chat.shared.protocol import packet
from chat.shared.utils import configure_logging

load_dotenv()
logger = configure_logging("chat.client", os.getenv("LOG_LEVEL", "INFO"))


class UIPort(Protocol):
    """Everything the client needs to render itself, implemented by the UI."""

    def add_message(self, sender: str, text: str, status: str = "") -> None: ...
    def add_image(self, sender: str, path: Path, caption: str = "") -> None: ...
    def clear_messages(self) -> None: ...
    def set_friend_typing(self, typing: bool) -> None: ...
    def set_friend(self, name: str) -> None: ...
    def set_friend_status(self, status: str) -> None: ...
    def set_self_status(self, status: str) -> None: ...
    def set_online(self, online: bool) -> None: ...
    def set_ping(self, ping_ms: int) -> None: ...
    def set_executing(self, command: str | None) -> None: ...
    def set_command_panel_visible(self, visible: bool) -> None: ...
    def set_command_help(self, commands: list[tuple[str, str]]) -> None: ...
    def start_transfer(self, label: str, total: int | None) -> None: ...
    def progress_transfer(self, current: int, total: int | None) -> None: ...
    def finish_transfer(self) -> None: ...
    def request_exit(self) -> None: ...


class ChatClient:
    def __init__(self, ui: UIPort) -> None:
        self.ui = ui
        self.username = os.environ["USERNAME"]
        self.password = os.environ["PASSWORD"]
        self.server = os.getenv("SERVER", "ws://127.0.0.1:8000/ws")
        self.http_server = os.getenv(
            "HTTP_SERVER", self.server.replace("ws://", "http://").replace("/ws", "")
        )
        self.download_dir = os.getenv("DOWNLOAD_DIR", "chat/client/downloads")
        self.crypto = MessageCrypto(self.password)
        self.incoming: asyncio.Queue[Packet] = asyncio.Queue()
        self.ws = WebSocketClient(
            self.server, self.username, self.password, self.incoming
        )
        self.notifier = Notifier(os.getenv("NOTIFICATIONS", "true").lower() == "true")
        self.ping = PingTracker()
        self.running = True
        self._typing = False
        self._last_activity_at = time.monotonic()
        self._presence_status = "online"
        self._input_history: list[str] = []
        self._history_index: int | None = None
        self.ui_config_path = Path.home() / ".pychat_ui.json"
        self.current_dir = Path.cwd()
        self.command_panel_visible = True
        self.load_ui_preferences()

    @property
    def presence_status(self) -> str:
        return self._presence_status

    def show(self, message: str) -> None:
        self.ui.add_message("System", message)

    def clear_screen(self) -> None:
        self.ui.clear_messages()

    async def notify_command(self, name: str) -> None:
        await self.ws.send(packet(PacketType.COMMAND, self.username, command=name))

    async def set_presence_status(self, status: str) -> None:
        if self._presence_status == status:
            return
        self._presence_status = status
        self.ui.set_self_status(status)
        await self.ws.send(packet(PacketType.PRESENCE, self.username, status=status))

    def mark_activity(self) -> None:
        self._last_activity_at = time.monotonic()

    def load_ui_preferences(self) -> None:
        try:
            data = json.loads(self.ui_config_path.read_text())
        except (OSError, json.JSONDecodeError):
            return
        self.command_panel_visible = bool(data.get("command_panel_visible", True))

    def save_ui_preferences(self) -> None:
        self.ui_config_path.write_text(
            json.dumps({"command_panel_visible": self.command_panel_visible}, indent=2)
        )

    def set_command_panel(self, mode: str) -> None:
        normalized = mode.lower()
        if normalized in {"hide", "hidden"}:
            self.command_panel_visible = False
            self.ui.set_command_panel_visible(False)
            self.show(
                "Command panel hidden for this session. Use /commands show to restore it."
            )
        elif normalized in {"off", "forever"}:
            self.command_panel_visible = False
            self.ui.set_command_panel_visible(False)
            self.save_ui_preferences()
            self.show(
                "Command panel hidden permanently. Use /commands show to restore it."
            )
        elif normalized in {"show", "on"}:
            self.command_panel_visible = True
            self.ui.set_command_panel_visible(True)
            self.save_ui_preferences()
            self.show("Command panel shown.")
        else:
            self.show("Usage: /commands show|hide|off")

    def resolve_local_path(self, path: str) -> Path:
        expanded = Path(path).expanduser()
        if expanded.is_absolute():
            return expanded
        return (self.current_dir / expanded).resolve()

    def print_working_directory(self) -> None:
        self.show(str(self.current_dir))

    def list_directory(self, path: str | None = None) -> None:
        directory = self.resolve_local_path(path) if path else self.current_dir
        if not directory.is_dir():
            self.show(f"Not a directory: {directory}")
            return
        entries = sorted(
            directory.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())
        )
        rendered = (
            "  ".join(
                f"{entry.name}/" if entry.is_dir() else entry.name for entry in entries
            )
            or "<empty>"
        )
        self.show(rendered)

    def change_directory(self, path: str) -> None:
        directory = self.resolve_local_path(path)
        if not directory.is_dir():
            self.show(f"Not a directory: {directory}")
            return
        self.current_dir = directory
        os.chdir(directory)
        self.show(str(self.current_dir))

    async def stop(self) -> None:
        if not self.running:
            return
        await self.set_typing(False)
        await self.set_presence_status("offline")
        self.running = False
        await asyncio.sleep(0.05)
        await self.ws.close()
        self.ui.request_exit()

    async def request_history(self, limit: int = 100) -> None:
        await self.ws.send(
            packet(PacketType.HISTORY_REQUEST, self.username, limit=limit)
        )

    async def ping_once(self) -> None:
        pkt = packet(PacketType.PING, self.username)
        self.ping.sent(pkt.id)
        await self.ws.send(pkt)

    def view_image(self, path: str) -> None:
        source = self.resolve_local_path(path)
        if not source.is_file():
            self.show(f"Not a file: {source}")
            return
        if not is_image_path(source):
            self.show(f"Not a recognized image type: {source.name}")
            return
        self.ui.add_image("You", source, source.name)

    async def send_file(self, path: str) -> None:
        try:
            source = self.resolve_local_path(path)

            def on_progress(current: int, total: int | None) -> None:
                self.ui.progress_transfer(current, total)

            self.ui.start_transfer(
                f"Uploading {source.name}",
                source.stat().st_size if source.is_file() else None,
            )
            try:
                result = await upload(
                    self.http_server, self.password, self.username, source, on_progress
                )
            finally:
                self.ui.finish_transfer()
            if is_image_path(source):
                self.ui.add_image(
                    "You", source, f"Sent {result['filename']} ({result['size']} bytes)"
                )
            else:
                self.show(f"Sent file {result['filename']} ({result['size']} bytes)")
        except Exception as exc:
            self.ui.finish_transfer()
            self.show(f"File send failed: {exc}")

    async def send_message(self, text: str) -> None:
        encrypted = self.crypto.encrypt(text)
        pkt = packet(PacketType.MESSAGE, self.username, encrypted_message=encrypted)
        self.ui.add_message("You", text, "✓")
        await self.ws.send(pkt)

    async def set_typing(self, typing: bool) -> None:
        if self._typing == typing:
            return
        self._typing = typing
        await self.ws.send(packet(PacketType.TYPING, self.username, typing=typing))

    def record_input_history(self, line: str) -> None:
        if line.strip():
            self._input_history.append(line)
        self._history_index = None

    def history_prev(self) -> str:
        if not self._input_history:
            return ""
        if self._history_index is None:
            self._history_index = len(self._input_history)
        self._history_index = max(0, self._history_index - 1)
        return self._input_history[self._history_index]

    def history_next(self) -> str:
        if not self._input_history or self._history_index is None:
            return ""
        self._history_index += 1
        if self._history_index >= len(self._input_history):
            self._history_index = len(self._input_history)
            return ""
        return self._input_history[self._history_index]

    async def submit_input(self, line: str) -> None:
        line = line.strip()
        await self.set_typing(False)
        if not line:
            return
        self.record_input_history(line)
        if line.startswith("/"):
            command_name = line.split(maxsplit=1)[0][1:]
            self.ui.set_executing(command_name)
            try:
                await registry.execute(self, line)
            finally:
                self.ui.set_executing(None)
        else:
            await self.send_message(line)

    async def incoming_loop(self) -> None:
        while self.running:
            pkt = await self.incoming.get()
            if pkt.type == PacketType.HISTORY:
                self.ui.clear_messages()
                for msg in pkt.payload.get("messages", []):
                    try:
                        text = self.crypto.decrypt(msg["encrypted_message"])
                    except Exception:
                        text = "<unable to decrypt>"
                    self.ui.add_message(
                        "You" if msg["sender"] == self.username else msg["sender"], text
                    )
            elif pkt.type == PacketType.MESSAGE and pkt.username != self.username:
                text = self.crypto.decrypt(str(pkt.payload["encrypted_message"]))
                self.ui.add_message(pkt.username, text)
                await self.notifier.message(pkt.username, text)
                await self.ws.send(
                    packet(
                        PacketType.RECEIPT,
                        self.username,
                        message_id=pkt.id,
                        status="read",
                    )
                )
            elif pkt.type == PacketType.PRESENCE:
                statuses = dict(pkt.payload.get("statuses", {}))
                online = [
                    u for u in pkt.payload.get("online", []) if u != self.username
                ]
                self.ui.set_online(bool(online))
                if online:
                    self.ui.set_friend(online[0])
                    self.ui.set_friend_status(str(statuses.get(online[0], "online")))
                elif pkt.username != self.username and pkt.username != "server":
                    self.ui.set_friend(pkt.username)
                    self.ui.set_friend_status(str(pkt.payload.get("status", "offline")))
                else:
                    self.ui.set_friend_status("offline")
            elif pkt.type == PacketType.TYPING:
                self.ui.set_friend_typing(bool(pkt.payload.get("typing")))
            elif pkt.type == PacketType.COMMAND and pkt.username != self.username:
                self.show(
                    f"{pkt.username} used /{pkt.payload.get('command', 'unknown')}"
                )
            elif pkt.type == PacketType.PONG:
                ms = self.ping.received(str(pkt.payload.get("echo")))
                if ms is not None:
                    self.ui.set_ping(ms)
            elif (
                pkt.type == PacketType.FILE
                and pkt.payload.get("sender") != self.username
            ):
                filename = str(pkt.payload["filename"])

                def on_progress(current: int, total: int | None) -> None:
                    self.ui.progress_transfer(current, total)

                self.ui.start_transfer(f"Downloading {filename}", None)
                try:
                    saved = await download(
                        self.http_server,
                        str(pkt.payload["id"]),
                        filename,
                        self.download_dir,
                        on_progress,
                    )
                finally:
                    self.ui.finish_transfer()
                if is_image_path(saved):
                    self.ui.add_image(pkt.username, saved, f"Sent {filename}")
                else:
                    self.show(f"Downloaded file to {saved}")

    async def ping_loop(self) -> None:
        while self.running:
            await self.ping_once()
            await asyncio.sleep(PING_INTERVAL_SECONDS)

    async def presence_loop(self) -> None:
        while self.running:
            status = (
                "idle"
                if time.monotonic() - self._last_activity_at >= IDLE_TIMEOUT_SECONDS
                else "online"
            )
            await self.set_presence_status(status)
            await asyncio.sleep(2)


def main() -> None:
    """Entrypoint kept here for backwards compatibility (``python -m chat.client.client``).

    The actual UI lives in :mod:`chat.client.ui`; imported lazily so this
    module has no hard dependency on Textual.
    """

    from chat.client.ui import main as ui_main

    ui_main()


if __name__ == "__main__":
    main()
