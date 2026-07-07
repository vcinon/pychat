"""Streaming file upload and download helpers."""

from __future__ import annotations

from pathlib import Path

import aiofiles
import httpx
from rich.progress import Progress

from chat.shared.constants import CHUNK_SIZE
from chat.shared.utils import ensure_dir


async def upload(http_server: str, password: str, username: str, path: str) -> dict[str, object]:
    source = Path(path).expanduser()
    if not source.is_file():
        raise FileNotFoundError(path)
    with Progress() as progress:
        task = progress.add_task(f"Uploading {source.name}", total=source.stat().st_size)

        class ProgressFile:
            def __init__(self, filename: Path) -> None:
                self._handle = filename.open("rb")

            def read(self, size: int = CHUNK_SIZE) -> bytes:
                chunk = self._handle.read(size)
                progress.update(task, advance=len(chunk))
                return chunk

            def close(self) -> None:
                self._handle.close()

        stream = ProgressFile(source)
        try:
            async with httpx.AsyncClient(timeout=None) as client:
                files = {"file": (source.name, stream)}
                response = await client.post(f"{http_server}/files", data={"password": password, "sender": username}, files=files)
                response.raise_for_status()
                return response.json()
        finally:
            stream.close()


async def download(http_server: str, file_id: str, filename: str, download_dir: str) -> Path:
    destination = ensure_dir(download_dir) / Path(filename).name
    async with httpx.AsyncClient(timeout=None) as client:
        async with client.stream("GET", f"{http_server}/files/{file_id}/{Path(filename).name}") as response:
            response.raise_for_status()
            total = int(response.headers.get("content-length", "0")) or None
            with Progress() as progress:
                task = progress.add_task(f"Downloading {filename}", total=total)
                async with aiofiles.open(destination, "wb") as out:
                    async for chunk in response.aiter_bytes(CHUNK_SIZE):
                        await out.write(chunk)
                        progress.update(task, advance=len(chunk))
    return destination
