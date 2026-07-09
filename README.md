# pychat

A private, encrypted two-person chat app with a terminal UI (built on
[Textual](https://textual.textualize.io/)) and a FastAPI server.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in USERNAME, PASSWORD, SERVER
```

Run the server: `python -m chat.server.main` (or `uvicorn chat.server.main:app`)
Run the client: `python -m chat.client.client`

## Message formatting

The client understands a small set of Markdown-like formatting and renders
it locally (formatting is never sent over the wire -- messages stay plain
text so both ends can render them however they like):

| Syntax                | Result                          |
|------------------------|----------------------------------|
| `**bold**`             | **bold**                        |
| `*italic*` / `_italic_`| *italic*                        |
| `~~strike~~`           | ~~strikethrough~~                |
| `` `code` ``           | inline code, highlighted        |
| ` ```lang\ncode\n``` `| a bordered code/command box     |
| bare `https://...`     | underlined, clickable link      |

Because formatting is applied only to *your own terminal's* rendering of a
message, a message from a peer can't inject Rich/Textual markup into your
UI -- any literal `[...]`-style text they send is shown escaped.

## Images

- `/img PATH` previews a local image file inline in the chat, using
  whichever terminal graphics protocol your terminal emulator supports
  (Sixel, Kitty/TGP, or a Unicode-block fallback) via `textual-image`.
- Files sent or received via `/send FILE` are automatically shown as an
  inline preview when they're a recognized image type
  (png/jpg/jpeg/gif/bmp/webp/tiff/ico).
- If your terminal can't render graphics (or `textual-image`/`pillow`
  aren't installed), you'll see a text placeholder with the file path
  instead -- the chat keeps working either way.
- `/status` shows which protocol was picked (e.g. `image preview: tgp`).

### If images don't show up (Ghostty, WezTerm, or over SSH)

`textual-image`'s automatic detection queries the terminal once at
startup and waits **up to 100ms** for a reply. That's a race: it can
easily misdetect a terminal that genuinely supports the Kitty graphics
protocol (Ghostty, WezTerm, Konsole) as unsupported, especially over SSH
or inside tmux/screen -- Alacritty, on the other hand, has no image
protocol support at all, so it will never show inline previews no matter
what.

This client applies a `TERM`/`TERM_PROGRAM`-based heuristic on top of that
auto-detection to catch known Kitty-protocol terminals it would otherwise
miss. But when you SSH into a remote host, Ghostty's `TERM` is often reset
to `xterm-256color` (because the remote lacks Ghostty's terminfo entry)
and `TERM_PROGRAM` may not be forwarded at all -- in that case even the
heuristic can't tell. If `/status` shows `auto` and images still aren't
appearing, force the protocol explicitly:

```bash
# in your .env, or exported before running the client
PYCHAT_IMAGE_PROTOCOL=tgp       # Ghostty, Kitty, WezTerm, Konsole
PYCHAT_IMAGE_PROTOCOL=sixel     # xterm and other Sixel-capable terminals
PYCHAT_IMAGE_PROTOCOL=halfcell  # forces a colored-block fallback (no protocol needed)
PYCHAT_IMAGE_PROTOCOL=unicode   # most compatible fallback
```

For a real SSH session with Ghostty specifically, also see Ghostty's own
[terminfo/SSH docs](https://ghostty.org/docs/help/terminfo) -- installing
its terminfo on the remote host (or using `ghostty +ssh`) keeps `TERM` as
`xterm-ghostty` end-to-end, which then lets our heuristic detect it
correctly without needing the override.

## Running the client as a background service (systemd)

The client is a terminal UI, so "running in the background" means running
it inside a detached [tmux](https://github.com/tmux/tmux) session that
`systemd --user` supervises -- you can still attach to see and use it live,
then detach, leaving it running.

```bash
# one-time setup
sudo apt install tmux          # or: brew install tmux
cp .env.example .env && $EDITOR .env

# install, enable at login, and start
./systemd/install_client_service.sh install

# check on it
systemctl --user status pychat-client
tmux attach -t pychat-client   # Ctrl-b d to detach again

# stop / remove
./systemd/install_client_service.sh uninstall
```

Under the hood this installs `systemd/pychat-client.service.template` as
`~/.config/systemd/user/pychat-client.service`, filled in with your paths,
and uses `chat/client/service.py` (also usable directly:
`python -m chat.client.service {start,stop,restart,status,attach}`) to
start/stop the tmux-wrapped client and track its PID for systemd.

`loginctl enable-linger` is enabled automatically so the service keeps
running after you log out / close your SSH session.
