"""Textual terminal UI for the chat client.

This module contains *only* presentation code. All networking, protocol,
and application state lives in :mod:`chat.client.client`; this module talks
to it exclusively through the public methods of ``ChatClient`` and by
implementing the ``UIPort`` protocol it defines.
"""

from __future__ import annotations

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.markup import escape
from textual.reactive import reactive
from textual.timer import Timer
from textual.widgets import Footer, Input, Label, ProgressBar, Static

from chat.client.client import ChatClient
from chat.client.commands import registry
from chat.shared.constants import APP_NAME, TYPING_TIMEOUT_SECONDS

# Colors mirrored from the original Rich UI's OPENCLAW palette.
COLORS = {
    "text": "#E8E3D5",
    "dim": "#7B7F87",
    "accent": "#F6C453",
    "accent_soft": "#F2A65A",
    "border": "#3C414B",
    "system": "#9BA3B2",
    "success": "#7DD3A5",
    "quote": "#8CC8FF",
    "error": "#F97066",
}

MAX_MESSAGES = 500


class StatusBar(Static):
    """Two-line header: your own presence on top, friend presence + ping below."""

    friend: reactive[str] = reactive("Friend")
    friend_status: reactive[str] = reactive("offline")
    self_status: reactive[str] = reactive("online")
    ping_ms: reactive[int | None] = reactive(None)

    @staticmethod
    def _marker(status: str) -> str:
        if status == "online":
            return f"[{COLORS['success']}]\u25cf[/] Online"
        elif status == "idle":
            return f"[{COLORS['accent_soft']}]\u25d0[/] Idle"
        return f"[{COLORS['dim']}]\u25cb[/] Offline"

    def render(self) -> str:
        self_line = f"[{COLORS['dim']}]You[/] {self._marker(self.self_status)}"
        friend_line = (
            # f"[bold {COLORS['accent']}]{APP_NAME}[/]  "
            f"[{COLORS['text']}]{escape(self.friend)}[/] {self._marker(self.friend_status)}"
        )
        if self.friend_status == "online" and self.ping_ms is not None:
            friend_line += f" [{COLORS['dim']}]({self.ping_ms} ms)[/]"
        return f"{self_line}\n{friend_line}"


class MessageLog(VerticalScroll):
    """Scrollable chat history."""

    def add_message(self, sender: str, text: str, status: str = "") -> None:
        if sender == "System":
            sender_color = COLORS["system"]
        elif sender == "You":
            sender_color = COLORS["accent"]
        else:
            sender_color = COLORS["quote"]
        markup = f"[bold {sender_color}]{escape(sender)}:[/] [{COLORS['text']}]{escape(text)}[/]"
        if status:
            markup += f" [{COLORS['dim']}]{escape(status)}[/]"
        was_at_bottom = self._is_scrolled_to_end()
        self.mount(Static(markup, classes="message"))
        self._trim()
        if was_at_bottom:
            self.scroll_end(animate=False)

    def clear_messages(self) -> None:
        self.remove_children()

    def _trim(self) -> None:
        children = self.children
        overflow = len(children) - MAX_MESSAGES
        for widget in children[:overflow]:
            widget.remove()

    def _is_scrolled_to_end(self) -> bool:
        return self.scroll_y >= self.max_scroll_y - 1


class CommandPanel(VerticalScroll):
    """Sidebar listing available slash commands and key hints."""

    def set_commands(self, commands: list[tuple[str, str]]) -> None:
        self.remove_children()
        rows = [
            Static(
                f"[{COLORS['accent']}]{escape(f'/{name}'):<13}[/] [{COLORS['dim']}]{escape(desc)}[/]",
                classes="command-row",
            )
            for name, desc in commands
        ]
        self.mount_all(rows)
        self.mount(
            Static(
                f"[{COLORS['dim']}]Tab autocomplete \u2022 \u2191/\u2193 history[/]\n"
                f"[{COLORS['dim']}]PageUp/PageDown scroll messages[/]\n"
                f"[{COLORS['dim']}]/commands hide|show|off[/]",
                classes="command-hint",
            )
        )


class TransferPanel(Horizontal):
    """Progress indicator shown during file uploads/downloads."""

    def compose(self) -> ComposeResult:
        yield Label("", id="transfer-label")
        yield ProgressBar(id="transfer-bar", show_eta=False)

    def start(self, label: str, total: int | None) -> None:
        self.query_one("#transfer-label", Label).update(label)
        self.query_one(ProgressBar).update(total=total, progress=0)
        self.remove_class("hidden")

    def progress(self, current: int, total: int | None) -> None:
        bar = self.query_one(ProgressBar)
        if total is not None:
            bar.update(total=total, progress=current)
        else:
            bar.update(progress=current)

    def finish(self) -> None:
        self.add_class("hidden")


class ChatInput(Input):
    """The message/command entry box.

    Extra key bindings delegate to app-level actions so history navigation,
    autocompletion, and chat scrolling work while the input has focus.
    """

    BINDINGS = [
        Binding("tab", "app.autocomplete", "Autocomplete", show=False),
        Binding("up", "app.history_prev", "Previous", show=False),
        Binding("down", "app.history_next", "Next", show=False),
        Binding("pageup", "app.scroll_chat(-1)", "Scroll up", show=False),
        Binding("pagedown", "app.scroll_chat(1)", "Scroll down", show=False),
    ]


class ChatApp(App[None]):
    """Textual application implementing the chat client's UI."""

    CSS_PATH = "chat.tcss"
    TITLE = APP_NAME

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit", priority=True, show=True),
        Binding("ctrl+d", "quit", "Quit", priority=True, show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.client = ChatClient(self)
        self._typing_timer: Timer | None = None
        self._executing_command: str | None = None
        self._friend_typing = False
        self._suppress_typing_signal = False
        self._online = False

    # -- Composition -----------------------------------------------------

    def compose(self) -> ComposeResult:
        yield StatusBar(id="status-bar")
        with Horizontal(id="body"):
            with Vertical(id="chat-pane"):
                yield MessageLog(id="message-log")
                yield Static("", id="activity-indicator", classes="hidden")
                yield TransferPanel(id="transfer-panel", classes="hidden")
            yield CommandPanel(id="commands-panel")
        yield ChatInput(placeholder="Message, or /command\u2026", id="message-input")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one(StatusBar).self_status = self.client.presence_status
        self.query_one(CommandPanel).set_commands(registry.help_items())
        self.set_command_panel_visible(self.client.command_panel_visible)
        self.query_one(ChatInput).focus()
        self.run_worker(self.client.ws.run(), name="websocket")
        self.run_worker(self.client.incoming_loop(), name="incoming")
        self.run_worker(self.client.ping_loop(), name="ping")
        self.run_worker(self.client.presence_loop(), name="presence")

    # -- Input handling ----------------------------------------------------

    @on(Input.Submitted, "#message-input")
    async def handle_submit(self, event: Input.Submitted) -> None:
        value = event.value
        event.input.value = ""
        self._cancel_typing_timer()
        await self.client.submit_input(value)

    @on(Input.Changed, "#message-input")
    async def handle_change(self, event: Input.Changed) -> None:
        if self._suppress_typing_signal:
            self._suppress_typing_signal = False
            return
        self.client.mark_activity()
        if event.value:
            self._reset_typing_timer()
            await self.client.set_typing(True)
        else:
            self._cancel_typing_timer()
            await self.client.set_typing(False)

    def _reset_typing_timer(self) -> None:
        if self._typing_timer is not None:
            self._typing_timer.stop()
        self._typing_timer = self.set_timer(
            TYPING_TIMEOUT_SECONDS, self._on_typing_timeout
        )

    def _cancel_typing_timer(self) -> None:
        if self._typing_timer is not None:
            self._typing_timer.stop()
            self._typing_timer = None

    async def _on_typing_timeout(self) -> None:
        self._typing_timer = None
        await self.client.set_typing(False)

    # -- Actions (bound to keys on ChatInput / the app) --------------------

    def _set_input_value(self, value: str) -> None:
        """Update the input's text without signalling a "typing" event."""

        input_widget = self.query_one(ChatInput)
        if input_widget.value != value:
            self._suppress_typing_signal = True
        input_widget.value = value
        input_widget.cursor_position = len(value)

    def action_autocomplete(self) -> None:
        input_widget = self.query_one(ChatInput)
        completed = registry.complete(input_widget.value)
        if completed is not None:
            self._set_input_value(completed)

    def action_history_prev(self) -> None:
        self._set_input_value(self.client.history_prev())

    def action_history_next(self) -> None:
        self._set_input_value(self.client.history_next())

    def action_scroll_chat(self, direction: int) -> None:
        message_log = self.query_one(MessageLog)
        if direction < 0:
            message_log.scroll_page_up()
        else:
            message_log.scroll_page_down()

    async def action_quit(self) -> None:
        await self.client.stop()

    # -- UIPort implementation, called by ChatClient -----------------------

    def add_message(self, sender: str, text: str, status: str = "") -> None:
        self.query_one(MessageLog).add_message(sender, text, status)

    def clear_messages(self) -> None:
        self.query_one(MessageLog).clear_messages()

    def set_friend_typing(self, typing: bool) -> None:
        self._friend_typing = typing
        self._update_activity_indicator()

    def set_friend(self, name: str) -> None:
        self.query_one(StatusBar).friend = name

    def set_friend_status(self, status: str) -> None:
        self.query_one(StatusBar).friend_status = status

    def set_self_status(self, status: str) -> None:
        self.query_one(StatusBar).self_status = status

    def set_online(self, online: bool) -> None:
        # Tracked for parity with the original UI state; not currently
        # reflected visually since friend/friend_status already convey it.
        self._online = online

    def set_ping(self, ping_ms: int) -> None:
        self.query_one(StatusBar).ping_ms = ping_ms

    def set_executing(self, command: str | None) -> None:
        self._executing_command = command
        self._update_activity_indicator()

    def set_command_panel_visible(self, visible: bool) -> None:
        self.query_one("#commands-panel").set_class(not visible, "hidden")

    def set_command_help(self, commands: list[tuple[str, str]]) -> None:
        self.query_one(CommandPanel).set_commands(commands)

    def start_transfer(self, label: str, total: int | None) -> None:
        self.query_one(TransferPanel).start(label, total)

    def progress_transfer(self, current: int, total: int | None) -> None:
        self.query_one(TransferPanel).progress(current, total)

    def finish_transfer(self) -> None:
        self.query_one(TransferPanel).finish()

    def request_exit(self) -> None:
        self.exit()

    def _update_activity_indicator(self) -> None:
        indicator = self.query_one("#activity-indicator", Static)
        if self._executing_command:
            indicator.update(
                f"[{COLORS['accent']}]\u23f3 executing /{escape(self._executing_command)}[/]"
            )
            indicator.remove_class("hidden")
        elif self._friend_typing:
            friend = self.query_one(StatusBar).friend
            indicator.update(
                f"[italic {COLORS['accent_soft']}]{escape(friend)} is typing\u2026[/]"
            )
            indicator.remove_class("hidden")
        else:
            indicator.update("")
            indicator.add_class("hidden")


def main() -> None:
    try:
        ChatApp().run()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
