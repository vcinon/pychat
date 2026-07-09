"""Rich-markup rendering for chat message text.

Messages are plain text as they travel over the wire (they're encrypted, so
no HTML/markup can be embedded by a remote peer -- this module is purely a
*local* rendering step). It understands a small, forgiving subset of
Markdown plus automatic URL detection:

* ``**bold**``            -> bold text
* ``*italic*`` / ``_x_``  -> italic text
* ``~~strike~~``          -> strikethrough
* `` `inline code` ``     -> inline code styling
* ``` ```lang\\ncode``` ```  -> a bordered "command box" for multi-line code
* bare URLs                -> underlined, clickable (OSC 8) links

Everything here only ever *emits* Rich console markup (square-bracket
tags); it never interprets markup that arrives in message text, so a peer
can't inject formatting into your terminal. All literal text is escaped
with :func:`textual.markup.escape` before any tags are added.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from textual.markup import escape

# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

# Fenced code block: ```[lang]\n...\n``` (also tolerates a fence with no
# trailing newline before the closing marker, and single-line fences).
_CODE_BLOCK_RE = re.compile(r"```(?P<lang>[\w+-]*)\n?(?P<code>.*?)```", re.DOTALL)

# Inline code: `code`
_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")

# Bold: **text** (non-greedy, no nested **)
_BOLD_RE = re.compile(r"\*\*(?!\s)(.+?)(?<!\s)\*\*")

# Italic: *text* or _text_ -- avoids matching ** by requiring a single star
# not adjacent to another star, and avoids matching mid-word underscores
# like some_var_name.
_ITALIC_STAR_RE = re.compile(r"(?<!\*)\*(?!\s)(?!\*)(.+?)(?<!\s)(?<!\*)\*(?!\*)")
_ITALIC_UNDERSCORE_RE = re.compile(r"(?<![\w])_(?!\s)(.+?)(?<!\s)_(?![\w])")

# Strikethrough: ~~text~~
_STRIKE_RE = re.compile(r"~~(?!\s)(.+?)(?<!\s)~~")

# URLs: http(s)://... or www.... Stops at whitespace and common trailing
# punctuation so "check https://x.com/y." doesn't swallow the period.
_URL_RE = re.compile(
    r"""(?P<url>
        (?:https?://|www\.)
        [^\s<>\[\]"']+
    )""",
    re.VERBOSE | re.IGNORECASE,
)
_TRAILING_PUNCT = ".,!?:;)]}\"'"


@dataclass(frozen=True)
class FormattedMessage:
    """Result of formatting a chat message.

    ``markup`` is ready to hand to a Rich/Textual renderable. ``urls`` is
    the list of URLs found in the text, in order, so the UI can offer
    "open"/"copy" affordances without re-parsing the message.
    """

    markup: str
    urls: list[str]
    code_blocks: list[str]


def _strip_trailing_punct(url: str) -> tuple[str, str]:
    """Split off trailing punctuation that's probably sentence punctuation."""
    trailer = ""
    while url and url[-1] in _TRAILING_PUNCT:
        # Don't strip a closing paren/bracket that has a matching opener
        # inside the URL (common in wiki links).
        if url[-1] == ")" and url.count("(") > url.count(")"):
            break
        trailer = url[-1] + trailer
        url = url[:-1]
    return url, trailer


def _linkify(text: str, url_color: str, urls_out: list[str]) -> str:
    """Escape ``text`` and wrap bare URLs in clickable, colored markup."""

    out: list[str] = []
    last = 0
    for match in _URL_RE.finditer(text):
        raw = match.group("url")
        url, trailer = _strip_trailing_punct(raw)
        if not url:
            continue
        out.append(escape(text[last : match.start()]))
        urls_out.append(url)
        # Textual's markup parser requires link targets to be quoted when
        # they contain characters like ':' or '/'; escape any embedded
        # double-quotes in the URL itself just in case.
        safe_url = url.replace('"', "%22")
        out.append(f'[underline {url_color} link="{safe_url}"]{escape(url)}[/]')
        out.append(escape(trailer))
        last = match.start() + len(raw)
    out.append(escape(text[last:]))
    return "".join(out)


def _apply_inline_styles(text: str, colors: dict[str, str], urls_out: list[str]) -> str:
    """Apply bold/italic/strike/inline-code/URL styling to a single line.

    Inline code is handled first and its contents are protected from
    further markdown expansion (code shouldn't be re-interpreted), then
    URLs are linkified in the remaining plain segments, then bold/italic/
    strike are layered on top.
    """

    # Pull out inline code spans first so `**not bold**` inside code stays
    # literal, and so code content is never linkified.
    placeholders: list[str] = []

    def _stash_code(m: re.Match[str]) -> str:
        placeholders.append(m.group(1))
        return f"\x00{len(placeholders) - 1}\x00"

    stripped = _INLINE_CODE_RE.sub(_stash_code, text)

    # Bold / italic / strike operate on the markdown syntax directly, then
    # we escape + linkify the remaining literal runs.
    segments: list[tuple[str, str | None]] = [(stripped, None)]  # (text, style|None)

    def _split_on(pattern: re.Pattern[str], style: str, segs: list[tuple[str, str | None]]) -> list[tuple[str, str | None]]:
        result: list[tuple[str, str | None]] = []
        for seg_text, seg_style in segs:
            if seg_style is not None:
                result.append((seg_text, seg_style))
                continue
            pos = 0
            for m in pattern.finditer(seg_text):
                if m.start() > pos:
                    result.append((seg_text[pos : m.start()], None))
                result.append((m.group(1), style))
                pos = m.end()
            result.append((seg_text[pos:], None))
        return result

    segments = _split_on(_BOLD_RE, "bold", segments)
    segments = _split_on(_ITALIC_STAR_RE, "italic", segments)
    segments = _split_on(_ITALIC_UNDERSCORE_RE, "italic", segments)
    segments = _split_on(_STRIKE_RE, "strike", segments)

    rendered: list[str] = []
    for seg_text, seg_style in segments:
        if not seg_text:
            continue
        body = _linkify(seg_text, colors.get("link", "#8CC8FF"), urls_out)
        if seg_style == "bold":
            rendered.append(f"[bold]{body}[/]")
        elif seg_style == "italic":
            rendered.append(f"[italic]{body}[/]")
        elif seg_style == "strike":
            rendered.append(f"[strike]{body}[/]")
        else:
            rendered.append(body)

    result = "".join(rendered)

    # Restore inline code with its own styling. Code content is escaped but
    # never linkified/markdown-expanded.
    def _restore_code(m: re.Match[str]) -> str:
        idx = int(m.group(1))
        code = placeholders[idx]
        code_bg = colors.get("code_bg", "#2A2E37")
        code_fg = colors.get("code_fg", "#F6C453")
        return f"[{code_fg} on {code_bg}] {escape(code)} [/]"

    result = re.sub(r"\x00(\d+)\x00", _restore_code, result)
    return result


def _render_code_block(lang: str, code: str, colors: dict[str, str]) -> str:
    """Render a fenced code block as a small bordered box."""

    lines = code.strip("\n").split("\n") if code.strip("\n") else [""]
    width = max((len(line) for line in lines), default=0)
    width = max(width, len(lang) + 2, 1)

    border = colors.get("code_border", "#3C414B")
    fg = colors.get("code_fg", "#F6C453")
    bg = colors.get("code_bg", "#22262E")

    top_label = f" {lang} " if lang else ""
    top = "┌─" + top_label + "─" * max(0, width - len(top_label)) + "┐"
    bottom = "└" + "─" * (width + 2) + "┘"

    box_lines = [f"[{border}]{escape(top)}[/]"]
    for line in lines:
        padded = line.ljust(width)
        box_lines.append(f"[{border}]│[/] [{fg} on {bg}]{escape(padded)}[/] [{border}]│[/]")
    box_lines.append(f"[{border}]{escape(bottom)}[/]")
    return "\n".join(box_lines)


def format_message(text: str, colors: dict[str, str] | None = None) -> FormattedMessage:
    """Convert plain chat text into Rich markup with markdown + URL support.

    ``colors`` may supply ``link``, ``code_fg``, ``code_bg``, and
    ``code_border`` overrides; sensible defaults matching the app's theme
    are used otherwise.
    """

    colors = colors or {}
    urls: list[str] = []
    code_blocks: list[str] = []

    pieces: list[str] = []
    pos = 0
    for match in _CODE_BLOCK_RE.finditer(text):
        before = text[pos : match.start()]
        if before:
            pieces.append(_apply_inline_styles(before, colors, urls))
        lang = match.group("lang") or ""
        code = match.group("code")
        code_blocks.append(code.strip("\n"))
        pieces.append(_render_code_block(lang, code, colors))
        pos = match.end()
    remainder = text[pos:]
    if remainder or not pieces:
        pieces.append(_apply_inline_styles(remainder, colors, urls))

    return FormattedMessage(markup="".join(pieces), urls=urls, code_blocks=code_blocks)


def extract_urls(text: str) -> list[str]:
    """Return the list of URLs found in ``text`` without rendering markup."""

    urls: list[str] = []
    for match in _URL_RE.finditer(text):
        url, _ = _strip_trailing_punct(match.group("url"))
        if url:
            urls.append(url)
    return urls
