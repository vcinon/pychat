"""Protocol helpers for packet construction and validation."""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from .packet import Packet, PacketType


class ProtocolError(ValueError):
    """Raised when a packet cannot be decoded or validated."""


def decode_packet(raw: str | bytes) -> Packet:
    try:
        data = json.loads(raw)
        return Packet.model_validate(data)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise ProtocolError(str(exc)) from exc


def packet(packet_type: PacketType, username: str, **payload: Any) -> Packet:
    return Packet(type=packet_type, username=username, payload=payload)
