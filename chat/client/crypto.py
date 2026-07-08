"""Client-side authenticated encryption."""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet


class MessageCrypto:
    def __init__(self, password: str) -> None:
        key = base64.urlsafe_b64encode(hashlib.sha256(password.encode()).digest())
        self._fernet = Fernet(key)

    def encrypt(self, text: str) -> str:
        return self._fernet.encrypt(text.encode()).decode()

    def decrypt(self, token: str) -> str:
        return self._fernet.decrypt(token.encode()).decode()
