"""Terminal chat client entrypoint."""

from __future__ import annotations

import asyncio
import os
import sys
import time
import json
from pathlib import Path

from dotenv import load_dotenv

from chat.client.commands import registry
from chat.client.crypto import MessageCrypto
from chat.client.file_transfer import download, upload
from chat.client.notifications import Notifier
from chat.client.ping import PingTracker
from chat.client.textual_ui import ChatUI
from chat.client.websocket import WebSocketClient
from chat.shared.constants import IDLE_TIMEOUT_SECONDS, PING_INTERVAL_SECONDS, TYPING_TIMEOUT_SECONDS
from chat.shared.packet import Packet, PacketType
from chat.shared.protocol import packet
from chat.shared.utils import configure_logging

load_dotenv()
logger = configure_logging("chat.client", os.getenv("LOG_LEVEL", "INFO"))


class ChatClient:
    def __init__(self) -> None:
        self.username = os.environ["USERNAME"]
        self.password = os.environ["PASSWORD"]
        self.server = os.getenv("SERVER", "ws://127.0.0.1:8000/ws")
        self.http_server = os.getenv("HTTP_SERVER", self.server.replace("ws://", "http://").replace("/ws", ""))
        self.download_dir = os.getenv("DOWNLOAD_DIR", "chat/client/downloads")
        self.crypto = MessageCrypto(self.password)
        self.incoming: asyncio.Queue[Packet] = asyncio.Queue()
        self.ws = WebSocketClient(self.server, self.username, self.password, self.incoming)
        self.ui = ChatUI(self.username)
        self.ui.set_command_help(registry.help_items())
        self.ui.client_callback = self._handle_ui_callback
        self.notifier = Notifier(os.getenv("NOTIFICATIONS", "true").lower() == "true")
        self.ping = PingTracker()
        self.running = True
        self._typing = False
        self._last_input_at = 0.0
        self._last_activity_at = time.monotonic()
        self._presence_status = "online"
        self._input_history: list[str] = []
        self._history_index: int | None = None
        self.ui_config_path = Path.home() / ".pychat_ui.json"
        self.current_dir = Path.cwd()
        self.load_ui_preferences()

    def _handle_ui_callback(self, action: str, **kwargs) -> None:
        """Handle UI callbacks from Textual."""
        if action == "restore_history":
            self.restore_input_history(kwargs.get("up", False))
        elif action == "tab_complete":
            completed = registry.complete(self.ui.input_buffer)
            if completed:
                self.ui.input_buffer = completed
        elif action == "input_changed":
            self.mark_activity()
        elif action == "submit_input":
            asyncio.create_task(self.submit_input())

    def show(self, message: str) -> None:
        self.ui.add("System", message)

    async def notify_command(self, name: str) -> None:
        await self.ws.send(packet(PacketType.COMMAND, self.username, command=name))

    async def set_presence_status(self, status: str) -> None:
        if self._presence_status == status:
            return
        self._presence_status = status
        self.ui.self_status = status
        await self.ws.send(packet(PacketType.PRESENCE, self.username, status=status))

    def mark_activity(self) -> None:
        self._last_activity_at = time.monotonic()
        self._last_input_at = time.monotonic()

    def load_ui_preferences(self) -> None:
        try:
            data = json.loads(self.ui_config_path.read_text())
        except (OSError, json.JSONDecodeError):
            return
        self.ui.command_panel_visible = bool(data.get("command_panel_visible", True))

    def save_ui_preferences(self) -> None:
        self.ui_config_path.write_text(json.dumps({"command_panel_visible": self.ui.command_panel_visible}, indent=2))

    def set_command_panel(self, mode: str) -> None:
        normalized = mode.lower()
        if normalized in {"hide", "hidden"}:
            self.ui.command_panel_visible = False
            self.show("Command panel hidden for this session. Use /commands show to restore it.")
        elif normalized in {"off", "forever"}:
            self.ui.command_panel_visible = False
            self.save_ui_preferences()
            self.show("Command panel hidden permanently. Use /commands show to restore it.")
        elif normalized in {"show", "on"}:
            self.ui.command_panel_visible = True
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
        entries = sorted(directory.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower()))
        rendered = "  ".join(f"{entry.name}/" if entry.is_dir() else entry.name for entry in entries) or "<empty>"
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
        await self.set_typing(False)
        await self.set_presence_status("offline")
        self.running = False
        await asyncio.sleep(0.05)
        await self.ws.close()
        await self.ui.exit()

    async def request_history(self, limit: int = 100) -> None:
        await self.ws.send(packet(PacketType.HISTORY_REQUEST, self.username, limit=limit))

    async def ping_once(self) -> None:
        pkt = packet(PacketType.PING, self.username)
        self.ping.sent(pkt.id)
        await self.ws.send(pkt)

    async def send_file(self, path: str) -> None:
        try:
            source = self.resolve_local_path(path)
            result = await upload(self.http_server, self.password, self.username, source)
            self.show(f"Sent file {result['filename']} ({result['size']} bytes)")
        except Exception as exc:
            self.show(f"File send failed: {exc}")

    async def send_message(self, text: str) -> None:
        encrypted = self.crypto.encrypt(text)
        pkt = packet(PacketType.MESSAGE, self.username, encrypted_message=encrypted)
        self.ui.add("You", text, "✓ Sent")
        await self.ws.send(pkt)

    async def set_typing(self, typing: bool) -> None:
        if self._typing == typing:
            return
        self._typing = typing
        await self.ws.send(packet(PacketType.TYPING, self.username, typing=typing))

    async def submit_input(self) -> None:
        line = self.ui.input_buffer.strip()
        self.ui.input_buffer = ""
        await self.set_typing(False)
        if not line:
            return
        if line.startswith("/"):
            self.ui.executing_command = line.split(maxsplit=1)[0][1:]
            try:
                await registry.execute(self, line)
            finally:
                self.ui.executing_command = None
        else:
            await self.send_message(line)
        # Add to history
        if line:
            self._input_history.append(line)
        self._history_index = None

    def restore_input_history(self, up: bool) -> None:
        if not self._input_history:
            return
        if self._history_index is None:
            self._history_index = len(self._input_history)
        self._history_index += -1 if up else 1
        if self._history_index < 0:
            self._history_index = 0
        if self._history_index >= len(self._input_history):
            self._history_index = len(self._input_history)
            self.ui.input_buffer = ""
            return
        self.ui.input_buffer = self._input_history[self._history_index]

    async def incoming_loop(self) -> None:
        while self.running:
            try:
                pkt = await self.incoming.get()
            except asyncio.CancelledError:
                break
            
            if pkt.type == PacketType.HISTORY:
                self.ui.messages = []
                for msg in pkt.payload.get("messages", []):
                    try:
                        text = self.crypto.decrypt(msg["encrypted_message"])
                    except Exception:
                        text = "<unable to decrypt>"
                    self.ui.add("You" if msg["sender"] == self.username else msg["sender"], text)
            elif pkt.type == PacketType.MESSAGE and pkt.username != self.username:
                text = self.crypto.decrypt(str(pkt.payload["encrypted_message"]))
                self.ui.add(pkt.username, text)
                await self.notifier.message(pkt.username, text)
                await self.ws.send(packet(PacketType.RECEIPT, self.username, message_id=pkt.id, status="read"))
            elif pkt.type == PacketType.PRESENCE:
                statuses = dict(pkt.payload.get("statuses", {}))
                online = [u for u in pkt.payload.get("online", []) if u != self.username]
                self.ui.online = bool(online)
                if online:
                    self.ui.friend = online[0]
                    self.ui.friend_status = str(statuses.get(online[0], "online"))
                elif pkt.username != self.username and pkt.username != "server":
                    self.ui.friend = pkt.username
                    self.ui.friend_status = str(pkt.payload.get("status", "offline"))
                else:
                    self.ui.friend_status = "offline"
            elif pkt.type == PacketType.TYPING:
                self.ui.typing = bool(pkt.payload.get("typing"))
            elif pkt.type == PacketType.COMMAND and pkt.username != self.username:
                self.show(f"{pkt.username} used /{pkt.payload.get('command', 'unknown')}")
            elif pkt.type == PacketType.PONG:
                ms = self.ping.received(str(pkt.payload.get("echo")))
                if ms is not None:
                    self.ui.ping_ms = ms
            elif pkt.type == PacketType.FILE and pkt.payload.get("sender") != self.username:
                saved = await download(self.http_server, str(pkt.payload["id"]), str(pkt.payload["filename"]), self.download_dir)
                self.show(f"Downloaded file to {saved}")

    async def ping_loop(self) -> None:
        while self.running:
            try:
                await self.ping_once()
                await asyncio.sleep(PING_INTERVAL_SECONDS)
            except asyncio.CancelledError:
                break

    async def presence_loop(self) -> None:
        while self.running:
            try:
                status = "idle" if time.monotonic() - self._last_activity_at >= IDLE_TIMEOUT_SECONDS else "online"
                await self.set_presence_status(status)
                await asyncio.sleep(2)
            except asyncio.CancelledError:
                break

    async def typing_timeout_loop(self) -> None:
        """Monitor typing timeout."""
        while self.running:
            try:
                if self._typing and time.monotonic() - self._last_input_at >= TYPING_TIMEOUT_SECONDS:
                    await self.set_typing(False)
                await asyncio.sleep(0.5)
            except asyncio.CancelledError:
                break

    async def run(self) -> None:
        # Create background tasks
        ws_task = asyncio.create_task(self.ws.run())
        incoming_task = asyncio.create_task(self.incoming_loop())
        ping_task = asyncio.create_task(self.ping_loop())
        presence_task = asyncio.create_task(self.presence_loop())
        typing_task = asyncio.create_task(self.typing_timeout_loop())
        
        tasks = [ws_task, incoming_task, ping_task, presence_task, typing_task]
        
        try:
            # Run Textual app - this blocks until the app is closed
            await self.ui.run_async(inline=True, inline_no_clear=True)
        except KeyboardInterrupt:
            await self.stop()
        except Exception as e:
            logger.exception("Client error: %s", e)
            await self.stop()
        finally:
            self.running = False
            for task in tasks:
                if not task.done():
                    task.cancel()
            # Wait for all tasks to complete
            await asyncio.gather(*tasks, return_exceptions=True)


def main() -> None:
    try:
        asyncio.run(ChatClient().run())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        logger.exception("Fatal error: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
