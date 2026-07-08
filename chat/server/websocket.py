"""FastAPI WebSocket connection, presence, ping, receipts and history."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict

from fastapi import WebSocket, WebSocketDisconnect

from chat.shared.packet import Packet, PacketType
from chat.shared.protocol import ProtocolError, decode_packet, packet
from chat.shared.utils import iso_now

from .auth import valid_password
from .database import Database
from .models import StoredMessage

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self, db: Database, password: str) -> None:
        self.db = db
        self.password = password
        self.active: dict[str, WebSocket] = {}
        self.lock = asyncio.Lock()
        self.started_at = iso_now()

    async def authenticate(self, websocket: WebSocket) -> str | None:
        try:
            raw = await asyncio.wait_for(websocket.receive_text(), timeout=10)
            auth = decode_packet(raw)
        except Exception:
            await websocket.close(code=1008, reason="authentication required")
            return None
        if auth.type != PacketType.AUTH or not valid_password(str(auth.payload.get("password", "")), self.password):
            await websocket.send_text(packet(PacketType.AUTH_ERROR, "server", error="invalid password").json_text())
            await websocket.close(code=1008, reason="invalid password")
            return None
        username = auth.username
        async with self.lock:
            old = self.active.get(username)
            if old is not None:
                await old.close(code=1000, reason="new session connected")
            self.active[username] = websocket
        await websocket.send_text(packet(PacketType.AUTH_OK, "server", authenticated_username=username).json_text())
        await self.broadcast_presence()
        await self.send_history(websocket, username, 100)
        logger.info("%s connected", username)
        return username

    async def disconnect(self, username: str) -> None:
        async with self.lock:
            self.active.pop(username, None)
        await self.broadcast_presence()
        logger.info("%s disconnected", username)

    async def broadcast_presence(self) -> None:
        users = list(self.active)
        await self.broadcast(packet(PacketType.PRESENCE, "server", online=users))

    async def broadcast(self, pkt: Packet, exclude: str | None = None) -> None:
        dead: list[str] = []
        async with self.lock:
            targets = list(self.active.items())
        for username, ws in targets:
            if username == exclude:
                continue
            try:
                await ws.send_text(pkt.json_text())
            except Exception:
                dead.append(username)
        for username in dead:
            await self.disconnect(username)

    async def send_history(self, websocket: WebSocket, username: str, limit: int) -> None:
        rows = [asdict(m) for m in await self.db.history(limit)]
        await websocket.send_text(packet(PacketType.HISTORY, "server", messages=rows).json_text())

    async def handle(self, websocket: WebSocket) -> None:
        await websocket.accept()
        username = await self.authenticate(websocket)
        if username is None:
            return
        try:
            while True:
                raw = await websocket.receive_text()
                try:
                    pkt = decode_packet(raw)
                except ProtocolError as exc:
                    await websocket.send_text(packet(PacketType.ERROR, "server", error=str(exc)).json_text())
                    continue
                await self.dispatch(websocket, username, pkt)
        except WebSocketDisconnect:
            pass
        finally:
            await self.disconnect(username)

    async def dispatch(self, websocket: WebSocket, username: str, pkt: Packet) -> None:
        if pkt.type == PacketType.MESSAGE:
            encrypted = str(pkt.payload.get("encrypted_message", ""))
            await self.db.save_message(StoredMessage(pkt.id, username, pkt.timestamp, encrypted))
            await self.broadcast(pkt, exclude=None)
            await self.broadcast(packet(PacketType.RECEIPT, "server", message_id=pkt.id, status="delivered"), exclude=username)
        elif pkt.type == PacketType.HISTORY_REQUEST:
            await self.send_history(websocket, username, int(pkt.payload.get("limit", 100)))
        elif pkt.type == PacketType.RECEIPT:
            if pkt.payload.get("status") == "read":
                await self.db.mark_read(str(pkt.payload.get("message_id")), iso_now())
            await self.broadcast(pkt, exclude=username)
        elif pkt.type in {PacketType.TYPING, PacketType.PING, PacketType.PONG, PacketType.HEARTBEAT, PacketType.COMMAND}:
            if pkt.type == PacketType.PING:
                await websocket.send_text(packet(PacketType.PONG, "server", echo=pkt.id).json_text())
            await self.broadcast(pkt, exclude=username)
        elif pkt.type == PacketType.FILE:
            await self.broadcast(pkt, exclude=username)
        else:
            await websocket.send_text(packet(PacketType.ERROR, "server", error=f"unsupported packet {pkt.type}").json_text())
