"""Terminal chat client entrypoint."""

from __future__ import annotations

import asyncio
import os
import select
import sys
import termios
import time
import tty
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from dotenv import load_dotenv

from chat.client.commands import registry
from chat.client.crypto import MessageCrypto
from chat.client.file_transfer import download, upload
from chat.client.notifications import Notifier
from chat.client.ping import PingTracker
from chat.client.ui import ChatUI
from chat.client.websocket import WebSocketClient
from chat.shared.constants import PING_INTERVAL_SECONDS, TYPING_TIMEOUT_SECONDS
from chat.shared.packet import Packet, PacketType
from chat.shared.protocol import packet
from chat.shared.utils import configure_logging

load_dotenv()
logger = configure_logging("chat.client", os.getenv("LOG_LEVEL", "INFO"))


@contextmanager
def raw_terminal() -> Iterator[None]:
    """Temporarily read stdin one character at a time without terminal echo."""

    if not sys.stdin.isatty():
        yield
        return
    file_descriptor = sys.stdin.fileno()
    previous = termios.tcgetattr(file_descriptor)
    try:
        tty.setcbreak(file_descriptor)
        yield
    finally:
        termios.tcsetattr(file_descriptor, termios.TCSADRAIN, previous)


async def read_key(timeout: float = 0.25) -> str | None:
    """Read one keypress without letting stdin redraw over Rich's live UI."""

    def _read() -> str | None:
        readable, _, _ = select.select([sys.stdin], [], [], timeout)
        if not readable:
            return None
        return sys.stdin.read(1)

    return await asyncio.to_thread(_read)


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
        self.notifier = Notifier(os.getenv("NOTIFICATIONS", "true").lower() == "true")
        self.ping = PingTracker()
        self.running = True
        self._typing = False
        self._last_input_at = 0.0
        self.current_dir = Path.cwd()

    def show(self, message: str) -> None:
        self.ui.add("System", message)

    async def notify_command(self, name: str) -> None:
        await self.ws.send(packet(PacketType.COMMAND, self.username, command=name))

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
        self.running = False
        await self.ws.close()

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
            await registry.execute(self, line)
        else:
            await self.send_message(line)

    async def input_loop(self) -> None:
        with raw_terminal():
            while self.running:
                key = await read_key()
                if key is None:
                    if self._typing and time.monotonic() - self._last_input_at >= TYPING_TIMEOUT_SECONDS:
                        await self.set_typing(False)
                    continue
                if key in {"\x03", "\x04"}:  # Ctrl-C / Ctrl-D
                    await self.stop()
                    return
                if key in {"\r", "\n"}:
                    await self.submit_input()
                    continue
                if key == "\t":
                    completed = registry.complete(self.ui.input_buffer)
                    if completed:
                        self.ui.input_buffer = completed
                    continue
                if key in {"\x7f", "\b"}:
                    self.ui.input_buffer = self.ui.input_buffer[:-1]
                    if not self.ui.input_buffer:
                        await self.set_typing(False)
                    continue
                if key == "\x1b":  # Drop escape sequences such as arrow keys.
                    for _ in range(2):
                        await read_key(timeout=0.01)
                    continue
                if key.isprintable():
                    self.ui.input_buffer += key
                    self._last_input_at = time.monotonic()
                    await self.set_typing(True)

    async def incoming_loop(self) -> None:
        while self.running:
            pkt = await self.incoming.get()
            if pkt.type == PacketType.HISTORY:
                self.ui.messages.clear()
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
                online = [u for u in pkt.payload.get("online", []) if u != self.username]
                self.ui.online = bool(online)
                if online: self.ui.friend = online[0]
            elif pkt.type == PacketType.TYPING:
                self.ui.typing = bool(pkt.payload.get("typing"))
            elif pkt.type == PacketType.COMMAND and pkt.username != self.username:
                self.show(f"{pkt.username} used /{pkt.payload.get('command', 'unknown')}")
            elif pkt.type == PacketType.PONG:
                ms = self.ping.received(str(pkt.payload.get("echo")))
                if ms is not None: self.ui.ping_ms = ms
            elif pkt.type == PacketType.FILE and pkt.payload.get("sender") != self.username:
                saved = await download(self.http_server, str(pkt.payload["id"]), str(pkt.payload["filename"]), self.download_dir)
                self.show(f"Downloaded file to {saved}")

    async def ping_loop(self) -> None:
        while self.running:
            await self.ping_once()
            await asyncio.sleep(PING_INTERVAL_SECONDS)

    async def run(self) -> None:
        ws_task = asyncio.create_task(self.ws.run())
        with self.ui.live() as live:
            async def refresh() -> None:
                while self.running:
                    live.update(self.ui.render())
                    await asyncio.sleep(0.2)
            tasks = [ws_task, asyncio.create_task(self.incoming_loop()), asyncio.create_task(self.ping_loop()), asyncio.create_task(self.input_loop()), asyncio.create_task(refresh())]
            try:
                await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            finally:
                await self.stop()
                for task in tasks: task.cancel()


def main() -> None:
    asyncio.run(ChatClient().run())


if __name__ == "__main__":
    main()
