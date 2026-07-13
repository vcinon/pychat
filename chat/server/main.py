"""FastAPI entrypoint for the private chat server."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import aiofiles
from fastapi import FastAPI, File, Form, HTTPException, UploadFile, WebSocket
from fastapi.responses import FileResponse
from fastapi import UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from chat.shared.packet import PacketType
from chat.shared.protocol import packet
from chat.shared.utils import configure_logging, ensure_dir, iso_now

from .config import config
from .database import Database
from .models import StoredFile
from .websocket import ConnectionManager

logger = configure_logging("chat.server", config.log_level)
db = Database(config.database_path)
manager = ConnectionManager(db, config.password)
app = FastAPI(title="Private Chat", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "tauri://localhost",
        "http://localhost:1420",
        "http://127.0.0.1:1420",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup() -> None:
    ensure_dir(config.upload_dir)
    await db.init()
    logger.info("server ready")


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await manager.handle(websocket)


@app.post("/files")
async def upload_file(password: str = Form(...), sender: str = Form(...), file: UploadFile = File(...)) -> dict[str, str | int]:
    from .auth import valid_password

    if not valid_password(password, config.password):
        raise HTTPException(status_code=403, detail="invalid password")
    file_id = uuid4().hex
    safe_name = Path(file.filename or file_id).name
    destination = ensure_dir(config.upload_dir) / f"{file_id}_{safe_name}"
    size = 0
    async with aiofiles.open(destination, "wb") as out:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > config.max_file_size_bytes:
                destination.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail="file too large")
            await out.write(chunk)
    await db.save_file(StoredFile(file_id, safe_name, sender, iso_now(), size))
    await manager.broadcast(packet(PacketType.FILE, "server", id=file_id, filename=safe_name, sender=sender, size=size))
    return {"id": file_id, "filename": safe_name, "size": size}


@app.get("/files/{file_id}/{filename}")
async def download_file(file_id: str, filename: str) -> FileResponse:
    safe_name = Path(filename).name
    path = Path(config.upload_dir) / f"{file_id}_{safe_name}"
    if not path.exists():
        raise HTTPException(status_code=404, detail="file not found")
    return FileResponse(path, filename=safe_name)
