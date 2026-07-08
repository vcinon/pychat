"""Shared-secret WebSocket authentication."""

from __future__ import annotations

import hmac


def valid_password(provided: str, expected: str) -> bool:
    return hmac.compare_digest(provided.encode(), expected.encode())
