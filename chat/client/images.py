"""Inline image preview support for the chat client.

Terminals vary wildly in what they can display. This module renders images
using whichever graphics protocol the terminal actually supports (Sixel,
Kitty/TGP, or a Unicode half-block fallback that works everywhere) via the
``textual-image`` library, and degrades gracefully to a plain text
placeholder if that library isn't installed or the file can't be read.

A note on auto-detection: ``textual_image``'s "auto" mode probes the
terminal once, at import time, by sending an escape sequence and waiting
*up to 100ms* for a reply. That's inherently racy -- over SSH, inside
tmux/screen, or under any latency, a terminal that genuinely supports the
Kitty graphics protocol (e.g. Ghostty, WezTerm) can still get misdetected
as unsupported because its reply didn't land in that 100ms window. This
module works around that by preferring a ``TERM``/``TERM_PROGRAM``-based
heuristic for well-known Kitty-protocol terminals over the flaky probe,
and lets the person force a specific protocol via ``PYCHAT_IMAGE_PROTOCOL``
if auto-detection still guesses wrong for their setup.
"""

from __future__ import annotations

import os
from pathlib import Path

from textual.containers import Vertical
from textual.reactive import reactive
from textual.widgets import Static

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tiff", ".ico"}

# Terminals known to implement the Kitty graphics protocol (TGP) but whose
# reply to textual-image's capability probe isn't reliably caught within
# its 100ms timeout, especially over SSH or inside tmux/screen.
_KNOWN_TGP_TERM_PROGRAMS = {"ghostty", "wezterm", "konsole"}
_KNOWN_TGP_TERMS = {"xterm-kitty", "xterm-ghostty"}

_IMAGE_SUPPORT = False
_TextualImage = None  # type: ignore[assignment]
_PROTOCOL_USED = "none"


def _detect_widget_class():
    """Pick an image-rendering widget class, working around flaky auto-detect.

    Order of preference:
    1. ``PYCHAT_IMAGE_PROTOCOL`` env var, if set (``tgp`` | ``sixel`` |
       ``halfcell`` | ``unicode`` | ``auto``) -- always wins.
    2. A ``TERM``/``TERM_PROGRAM`` match against terminals known to support
       the Kitty graphics protocol, since textual-image's own probe can
       miss them.
    3. textual-image's built-in auto-detecting ``AutoImage``.
    """

    from textual_image.widget import AutoImage, HalfcellImage, SixelImage, TGPImage, UnicodeImage

    forced = os.environ.get("PYCHAT_IMAGE_PROTOCOL", "").strip().lower()
    by_name = {
        "tgp": TGPImage,
        "kitty": TGPImage,
        "sixel": SixelImage,
        "halfcell": HalfcellImage,
        "unicode": UnicodeImage,
        "auto": AutoImage,
    }
    if forced in by_name:
        return by_name[forced], forced

    term = os.environ.get("TERM", "").lower()
    term_program = os.environ.get("TERM_PROGRAM", "").lower()
    if (
        term in _KNOWN_TGP_TERMS
        or term_program in _KNOWN_TGP_TERM_PROGRAMS
        or "kitty" in term
        or "ghostty" in term
        or "wezterm" in term_program
    ):
        return TGPImage, "tgp (heuristic)"

    return AutoImage, "auto"


try:
    _TextualImage, _PROTOCOL_USED = _detect_widget_class()
    _IMAGE_SUPPORT = True
except Exception:  # pragma: no cover - optional dependency
    _TextualImage = None  # type: ignore[assignment]
    _IMAGE_SUPPORT = False


def image_support_status() -> str:
    """Human-readable summary of how images will be rendered, for /status."""
    if not _IMAGE_SUPPORT:
        return "image preview unavailable (textual-image not installed)"
    return f"image preview: {_PROTOCOL_USED} (override with PYCHAT_IMAGE_PROTOCOL=tgp|sixel|halfcell|unicode)"


def is_image_path(path: str | Path) -> bool:
    """Return True if ``path`` looks like a supported image file."""
    return Path(path).suffix.lower() in IMAGE_EXTENSIONS


class ImagePreview(Vertical):
    """A chat-log entry that shows an inline image with a caption.

    Falls back to a text placeholder (filename + a hint) when the
    ``textual-image`` dependency isn't available, the terminal can't render
    graphics, or the file can't be opened -- the chat keeps working either
    way, it just loses the pretty preview.
    """

    DEFAULT_CSS = """
    ImagePreview {
        height: auto;
        width: 1fr;
        padding: 0 0 1 0;
    }
    ImagePreview > .image-caption {
        color: #7B7F87;
        height: auto;
    }
    ImagePreview > .image-frame {
        height: auto;
        max-height: 20;
        width: auto;
        max-width: 60;
    }
    """

    def __init__(self, path: Path, caption: str, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._path = path
        self._caption = caption

    def compose(self):
        yield Static(self._caption, classes="image-caption")
        if _IMAGE_SUPPORT and self._path.is_file():
            try:
                yield _TextualImage(self._path, classes="image-frame")
                return
            except Exception:
                pass
        yield Static(
            f"[dim]\U0001f5bc  (preview unavailable in this terminal \u2014 {self._path})[/]",
            classes="image-frame",
        )
