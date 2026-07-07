"""Terminal chat client entrypoint."""

from __future__ import annotations

import asyncio
import os

from dotenv import load_dotenv

from chat.client.commands import registry
from chat.client.crypto import MessageCrypto
from chat.client.file_transfer import download, upload
from chat.client.notifications import Notifier
from chat.client.ping import PingTracker
from chat.client.ui import ChatUI
from chat.client.websocket import WebSocketClient
from chat.shared.constants import PING_INTERVAL_SECONDS
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
        self.notifier = Notifier(os.getenv("NOTIFICATIONS", "true").lower() == "true")
        self.ping = PingTracker()
        self.running = True

    def show(self, message: str) -> None:
        self.ui.add("System", message)

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
            result = await upload(self.http_server, self.password, self.username, path)
            self.show(f"Sent file {result['filename']} ({result['size']} bytes)")
        except Exception as exc:
            self.show(f"File send failed: {exc}")

    async def send_message(self, text: str) -> None:
        encrypted = self.crypto.encrypt(text)
        pkt = packet(PacketType.MESSAGE, self.username, encrypted_message=encrypted)
        self.ui.add("You", text, "✓ Sent")
        await self.ws.send(pkt)

    async def input_loop(self) -> None:
        while self.running:
            line = await asyncio.to_thread(input, "")
            if not line:
                continue
            if line.startswith("/"):
                await registry.execute(self, line)
            else:
                await self.send_message(line)

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
