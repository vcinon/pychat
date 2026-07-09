#!/usr/bin/env bash
# Installs the pychat client as a systemd --user service.
#
# The client is a terminal UI, so this runs it inside a detached tmux
# session (see chat/client/service.py) and lets systemd supervise that.
# You can still attach any time with: tmux attach -t pychat-client
#
# Usage:
#   ./systemd/install_client_service.sh install     # install + enable + start
#   ./systemd/install_client_service.sh uninstall    # stop + disable + remove
#   ./systemd/install_client_service.sh status        # show service status
#
# This installs a *user* unit (no root required), started at login and kept
# running via `loginctl enable-linger $USER` (done automatically here) so it
# also survives logout.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
SERVICE_NAME="pychat-client.service"
SESSION_NAME="pychat-client"
UNIT_DIR="${HOME}/.config/systemd/user"
UNIT_PATH="${UNIT_DIR}/${SERVICE_NAME}"
RUNTIME_DIR="${XDG_RUNTIME_DIR:-/tmp}"

require() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "error: '$1' is required but not found on PATH" >&2
    exit 1
  }
}

cmd_install() {
  require systemctl
  require tmux
  require python3

  if [ ! -f "${INSTALL_DIR}/.env" ]; then
    echo "warning: ${INSTALL_DIR}/.env not found. Copy .env.example to .env and" >&2
    echo "fill in USERNAME/PASSWORD/SERVER before starting the service." >&2
  fi

  mkdir -p "${UNIT_DIR}"

  PYTHON_BIN="$(command -v python3)"

  sed \
    -e "s#__INSTALL_DIR__#${INSTALL_DIR}#g" \
    -e "s#__PYTHON__#${PYTHON_BIN}#g" \
    -e "s#__SESSION_NAME__#${SESSION_NAME}#g" \
    -e "s#__RUNTIME_DIR__#${RUNTIME_DIR}#g" \
    "${SCRIPT_DIR}/pychat-client.service.template" > "${UNIT_PATH}"

  echo "wrote ${UNIT_PATH}"

  systemctl --user daemon-reload
  systemctl --user enable "${SERVICE_NAME}"
  systemctl --user start "${SERVICE_NAME}"

  # Let the user service keep running after the user logs out / SSH session
  # ends, which is normally required for tmux-backed background services.
  if command -v loginctl >/dev/null 2>&1; then
    loginctl enable-linger "$(whoami)" 2>/dev/null || \
      echo "note: could not enable lingering automatically; run:" \
           "'sudo loginctl enable-linger $(whoami)' to keep the service" \
           "running after logout." >&2
  fi

  echo "installed and started ${SERVICE_NAME}"
  echo "attach to the live UI with: tmux attach -t ${SESSION_NAME}  (detach: Ctrl-b d)"
  echo "check status with: systemctl --user status ${SERVICE_NAME}"
}

cmd_uninstall() {
  require systemctl
  systemctl --user stop "${SERVICE_NAME}" 2>/dev/null || true
  systemctl --user disable "${SERVICE_NAME}" 2>/dev/null || true
  rm -f "${UNIT_PATH}"
  systemctl --user daemon-reload
  if command -v tmux >/dev/null 2>&1; then
    tmux kill-session -t "${SESSION_NAME}" 2>/dev/null || true
  fi
  echo "uninstalled ${SERVICE_NAME}"
}

cmd_status() {
  require systemctl
  systemctl --user status "${SERVICE_NAME}" --no-pager || true
}

case "${1:-}" in
  install) cmd_install ;;
  uninstall) cmd_uninstall ;;
  status) cmd_status ;;
  *)
    echo "usage: $0 {install|uninstall|status}" >&2
    exit 2
    ;;
esac
