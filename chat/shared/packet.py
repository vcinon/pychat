"""Validated JSON packet primitives."""

from __future__ import annotations

from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from .utils import iso_now


class PacketType(StrEnum):
    AUTH = "auth"
    AUTH_OK = "auth_ok"
    AUTH_ERROR = "auth_error"
    MESSAGE = "message"
    HISTORY = "history"
    HISTORY_REQUEST = "history_request"
    RECEIPT = "receipt"
    TYPING = "typing"
    PRESENCE = "presence"
    PING = "ping"
    PONG = "pong"
    FILE = "file"
    ERROR = "error"
    COMMAND = "command"
    HEARTBEAT = "heartbeat"


class Packet(BaseModel):
    """Protocol packet exchanged over WebSockets."""

    model_config = ConfigDict(extra="forbid")

    type: PacketType
    id: str = Field(default_factory=lambda: uuid4().hex)
    timestamp: str = Field(default_factory=iso_now)
    username: str
    payload: dict[str, Any] = Field(default_factory=dict)

    def json_text(self) -> str:
        return self.model_dump_json()
