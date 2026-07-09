"""Streaming file upload and download helpers.

This module is intentionally UI-framework agnostic: progress is reported via
a plain callback so it can be wired up to any presentation layer (Textual,
a CLI, tests, ...) without importing that layer here.
"""

from __future__ import annotations

from collections.abc import Callable
from os import PathLike
from pathlib import Path

import aiofiles
import httpx

from chat.shared.constants import CHUNK_SIZE
from chat.shared.utils import ensure_dir

# Called as on_progress(bytes_transferred, total_bytes_or_None).
ProgressCallback = Callable[[int, int | None], None]


async def upload(
    http_server: str,
    password: str,
    username: str,
    path: str | PathLike[str],
    on_progress: ProgressCallback | None = None,
) -> dict[str, object]:
    source = Path(path).expanduser()
    if not source.is_file():
        raise FileNotFoundError(path)
    total = source.stat().st_size

    class ProgressFile:
        def __init__(self, filename: Path) -> None:
            self._handle = filename.open("rb")
            self._sent = 0

        def read(self, size: int = CHUNK_SIZE) -> bytes:
            chunk = self._handle.read(size)
            self._sent += len(chunk)
            if on_progress is not None:
                on_progress(self._sent, total)
            return chunk

        def close(self) -> None:
            self._handle.close()

    stream = ProgressFile(source)
    try:
        async with httpx.AsyncClient(timeout=None) as client:
            files = {"file": (source.name, stream)}
            response = await client.post(
                f"{http_server}/files",
                data={"password": password, "sender": username},
                files=files,
            )
            response.raise_for_status()
            return response.json()
    finally:
        stream.close()


async def download(
    http_server: str,
    file_id: str,
    filename: str,
    download_dir: str,
    on_progress: ProgressCallback | None = None,
) -> Path:
    destination = ensure_dir(download_dir) / Path(filename).name
    async with httpx.AsyncClient(timeout=None) as client:
        async with client.stream("GET", f"{http_server}/files/{file_id}/{Path(filename).name}") as response:
            response.raise_for_status()
            total = int(response.headers.get("content-length", "0")) or None
            received = 0
            async with aiofiles.open(destination, "wb") as out:
                async for chunk in response.aiter_bytes(CHUNK_SIZE):
                    await out.write(chunk)
                    received += len(chunk)
                    if on_progress is not None:
                        on_progress(received, total)
    return destination
