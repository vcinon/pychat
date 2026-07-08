"""Async SQLite persistence."""

from __future__ import annotations

import aiosqlite

from .models import StoredFile, StoredMessage


class Database:
    def __init__(self, path: str) -> None:
        self.path = path

    async def init(self) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.executescript(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    sender TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    encrypted_message TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS read_receipts (
                    message_id TEXT PRIMARY KEY,
                    read INTEGER NOT NULL DEFAULT 0,
                    read_timestamp TEXT,
                    FOREIGN KEY(message_id) REFERENCES messages(id)
                );
                CREATE TABLE IF NOT EXISTS files (
                    id TEXT PRIMARY KEY,
                    filename TEXT NOT NULL,
                    sender TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    size INTEGER NOT NULL
                );
                """
            )
            await db.commit()

    async def save_message(self, message: StoredMessage) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT OR IGNORE INTO messages(id, sender, timestamp, encrypted_message) VALUES (?, ?, ?, ?)",
                (message.id, message.sender, message.timestamp, message.encrypted_message),
            )
            await db.execute("INSERT OR IGNORE INTO read_receipts(message_id, read) VALUES (?, 0)", (message.id,))
            await db.commit()

    async def history(self, limit: int = 100) -> list[StoredMessage]:
        async with aiosqlite.connect(self.path) as db:
            rows = await db.execute_fetchall(
                "SELECT id, sender, timestamp, encrypted_message FROM messages ORDER BY timestamp ASC LIMIT ?",
                (limit,),
            )
        return [StoredMessage(*row) for row in rows]

    async def mark_read(self, message_id: str, timestamp: str) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT INTO read_receipts(message_id, read, read_timestamp) VALUES (?, 1, ?) "
                "ON CONFLICT(message_id) DO UPDATE SET read=1, read_timestamp=excluded.read_timestamp",
                (message_id, timestamp),
            )
            await db.commit()

    async def save_file(self, file: StoredFile) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT OR REPLACE INTO files(id, filename, sender, timestamp, size) VALUES (?, ?, ?, ?, ?)",
                (file.id, file.filename, file.sender, file.timestamp, file.size),
            )
            await db.commit()
