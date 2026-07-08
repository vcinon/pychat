"""Server-side data models."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class StoredMessage:
    id: str
    sender: str
    timestamp: str
    encrypted_message: str


@dataclass(slots=True, frozen=True)
class StoredFile:
    id: str
    filename: str
    sender: str
    timestamp: str
    size: int
