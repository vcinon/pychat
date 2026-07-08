"""Async reconnecting WebSocket client."""

from __future__ import annotations

import asyncio
import logging

import websockets
from websockets.client import WebSocketClientProtocol

from chat.shared.constants import HEARTBEAT_INTERVAL_SECONDS, PING_INTERVAL_SECONDS, RECONNECT_INITIAL_SECONDS, RECONNECT_MAX_SECONDS
from chat.shared.packet import Packet, PacketType
from chat.shared.protocol import decode_packet, packet

logger = logging.getLogger(__name__)


class WebSocketClient:
    def __init__(self, server: str, username: str, password: str, incoming: asyncio.Queue[Packet]) -> None:
        self.server = server
        self.username = username
        self.password = password
        self.incoming = incoming
        self.outbox: asyncio.Queue[Packet] = asyncio.Queue()
        self.stop_event = asyncio.Event()
        self.connected = asyncio.Event()
        self.ws: WebSocketClientProtocol | None = None

    async def send(self, pkt: Packet) -> None:
        await self.outbox.put(pkt)

    async def run(self) -> None:
        backoff = RECONNECT_INITIAL_SECONDS
        while not self.stop_event.is_set():
            try:
                async with websockets.connect(self.server, ping_interval=None, close_timeout=5) as ws:
                    self.ws = ws
                    await ws.send(packet(PacketType.AUTH, self.username, password=self.password).json_text())
                    auth = decode_packet(await ws.recv())
                    if auth.type != PacketType.AUTH_OK:
                        raise PermissionError(auth.payload.get("error", "authentication failed"))
                    self.connected.set(); backoff = RECONNECT_INITIAL_SECONDS
                    await asyncio.gather(self._reader(ws), self._writer(ws), self._heartbeats())
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.connected.clear(); logger.warning("connection lost: %s", exc)
                await asyncio.sleep(backoff); backoff = min(backoff * 2, RECONNECT_MAX_SECONDS)

    async def _reader(self, ws: WebSocketClientProtocol) -> None:
        async for raw in ws:
            try:
                await self.incoming.put(decode_packet(raw))
            except Exception as exc:
                logger.warning("bad packet ignored: %s", exc)

    async def _writer(self, ws: WebSocketClientProtocol) -> None:
        while True:
            pkt = await self.outbox.get()
            await ws.send(pkt.json_text())

    async def _heartbeats(self) -> None:
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)
            await self.send(packet(PacketType.HEARTBEAT, self.username))

    async def close(self) -> None:
        self.stop_event.set()
        if self.ws:
            await self.ws.close()
