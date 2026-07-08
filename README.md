# Private Chat

A lightweight, asynchronous, two-person private chat service for Linux. It includes a FastAPI server, a Rich terminal client, WebSocket realtime messaging, SQLite persistence, shared-secret authentication, client-side message encryption, presence, pings, receipts, notifications, reconnects, and file transfer.

## Installation

Requires Python 3.13+.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` on both machines. `PASSWORD` must match. Each user should set their own `USERNAME`.

## Configuration

```env
USERNAME=Yassin
PASSWORD=super_secret
SERVER=ws://127.0.0.1:8000/ws
HTTP_SERVER=http://127.0.0.1:8000
DATABASE_PATH=chat.db
NOTIFICATIONS=true
DOWNLOAD_DIR=chat/client/downloads
UPLOAD_DIR=chat/server/uploads
MAX_FILE_SIZE=500MB
LOG_LEVEL=INFO
```

## Running

Start the server:

```bash
uvicorn chat.server.main:app --host 0.0.0.0 --port 8000
```

Start a client:

```bash
python -m chat.client.client
```

## Commands

- `/help` shows registered commands.
- `/ping` measures latency.
- `/uptime` displays uptime-related status.
- `/send FILE` uploads and shares a file.
- `/pwd` shows the client's local working directory.
- `/ls [DIR]` lists local files.
- `/cd [DIR]` changes the client's local working directory used by `/send`.
- `/history [N]` reloads message history.
- `/clear` explains how to clear the live view.
- `/online` shows presence in the header.
- `/status` displays client status.
- `/version` displays the app version.
- `/quit` exits gracefully.

Press `Tab` while typing a command to autocomplete command names and local paths for `/send`, `/ls`, and `/cd`. When either user runs a slash command, the other client receives a small system notice showing which command was used.

## Architecture

```text
chat/
  server/   FastAPI, WebSocket routing, auth, SQLite, uploads
  client/   Rich UI, reconnecting WebSocket client, commands, crypto, transfers
  shared/   Packet models, protocol validation, constants, utilities
```

Messages are encrypted by the client with authenticated encryption before transmission. The server stores and relays ciphertext. The crypto boundary is intentionally isolated so the encryption scheme can be upgraded later without changing routing or storage.

## Reliability

The client uses automatic reconnect with exponential backoff, an offline outbox queue, heartbeats, periodic pings, and graceful shutdown. The server validates malformed packets and isolates connection failures so one broken client does not affect the other.

## Future Improvements

- Replace password-derived Fernet with a formal double-ratchet or age/X25519 design.
- Add optional TLS termination examples.
- Add packaging metadata and systemd units.
- Add exhaustive integration tests with two simulated clients.
