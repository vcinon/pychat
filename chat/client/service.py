"""Run the chat client as a background service.

The client is a Textual TUI: it needs a real terminal to render into, but
``systemd`` services don't have one. The standard fix -- used here -- is to
launch the TUI inside a *detached* ``tmux`` session. systemd then supervises
the tmux client process (via a PID file) for restart-on-crash and start/stop
control, while a person can still run ``tmux attach -t pychat-client`` (or
``chat-service attach``) at any time to see and use the chat UI live, then
detach again (Ctrl-b d) leaving it running in the background.

This module implements the small ``start`` / ``stop`` / ``restart`` /
``status`` / ``attach`` command surface that both the systemd unit and a
person on the command line use. See ``systemd/`` for the installer.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

SESSION_NAME = os.environ.get("PYCHAT_TMUX_SESSION", "pychat-client")
RUNTIME_DIR = Path(
    os.environ.get("XDG_RUNTIME_DIR") or os.environ.get("PYCHAT_RUNTIME_DIR") or "/tmp"
)
PID_FILE = RUNTIME_DIR / "pychat-client.pid"


def _require_tmux() -> str:
    tmux = shutil.which("tmux")
    if tmux is None:
        print(
            "error: tmux is required to run the client as a background service "
            "(it provides the terminal the TUI renders into). Install it with "
            "your package manager, e.g. `apt install tmux` / `brew install tmux`.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    return tmux


def _session_exists(tmux: str) -> bool:
    result = subprocess.run(
        [tmux, "has-session", "-t", SESSION_NAME],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def _pane_pid(tmux: str) -> int | None:
    """PID of the process running inside the tmux pane (the actual client)."""
    result = subprocess.run(
        [tmux, "list-panes", "-t", SESSION_NAME, "-F", "#{pane_pid}"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return None
    try:
        return int(result.stdout.strip().splitlines()[0])
    except ValueError:
        return None


def start() -> None:
    tmux = _require_tmux()
    if _session_exists(tmux):
        print(f"pychat client already running in tmux session '{SESSION_NAME}'")
        _write_pid_file(tmux)
        return

    python = sys.executable
    subprocess.run(
        [
            tmux,
            "new-session",
            "-d",
            "-s",
            SESSION_NAME,
            python,
            "-m",
            "chat.client.client",
        ],
        check=True,
    )
    # Give the child a moment to spawn so the pane PID is available.
    for _ in range(20):
        if _session_exists(tmux) and _pane_pid(tmux) is not None:
            break
        time.sleep(0.1)
    _write_pid_file(tmux)
    print(f"started pychat client in detached tmux session '{SESSION_NAME}'")
    print(f"attach any time with: tmux attach -t {SESSION_NAME}  (detach: Ctrl-b d)")


def _write_pid_file(tmux: str) -> None:
    pid = _pane_pid(tmux)
    if pid is None:
        return
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(pid))


def stop() -> None:
    tmux = shutil.which("tmux")
    if tmux is None or not _session_exists(tmux):
        print("pychat client is not running")
        PID_FILE.unlink(missing_ok=True)
        return
    subprocess.run([tmux, "kill-session", "-t", SESSION_NAME], check=False)
    PID_FILE.unlink(missing_ok=True)
    print(f"stopped pychat client (tmux session '{SESSION_NAME}')")


def restart() -> None:
    stop()
    time.sleep(0.3)
    start()


def status() -> None:
    tmux = shutil.which("tmux")
    if tmux is None or not _session_exists(tmux):
        print("pychat client: not running")
        raise SystemExit(1)
    pid = _pane_pid(tmux)
    print(f"pychat client: running (tmux session '{SESSION_NAME}', pid {pid})")


def attach() -> None:
    tmux = _require_tmux()
    if not _session_exists(tmux):
        print(f"no running session '{SESSION_NAME}' -- start it first with: chat-service start")
        raise SystemExit(1)
    os.execvp(tmux, [tmux, "attach", "-t", SESSION_NAME])


COMMANDS = {
    "start": start,
    "stop": stop,
    "restart": restart,
    "status": status,
    "attach": attach,
}


def main(argv: list[str] | None = None) -> None:
    argv = argv if argv is not None else sys.argv[1:]
    if not argv or argv[0] not in COMMANDS:
        names = ", ".join(COMMANDS)
        print(f"usage: python -m chat.client.service {{{names}}}", file=sys.stderr)
        raise SystemExit(2)
    COMMANDS[argv[0]]()


if __name__ == "__main__":
    main()
