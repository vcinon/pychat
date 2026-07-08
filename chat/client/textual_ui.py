"""Textual terminal UI for chat client."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from rich.text import Text
from rich.panel import Panel
from rich.table import Table
from textual.app import App, ComposeResult
from textual.containers import Container, Vertical
from textual.widgets import Header, Footer, Static
from textual.binding import Binding
from textual.reactive import reactive
from textual.message import Message
from textual.events import Key

from chat.shared.constants import APP_NAME

# Color palette matching original Rich UI (OPENCLAW theme)
OPENCLAW = {
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


@dataclass(frozen=True)
class CommandHelp:
    """Help information for a command."""
    name: str
    description: str


class MessageDisplay(Static):
    """Renders the chat message history."""

    messages: reactive[list[tuple[str, str, str]]] = reactive([], layout=True)
    message_scroll: reactive[int] = reactive(0, layout=True)
    typing: reactive[bool] = reactive(False)
    executing_command: reactive[str | None] = reactive(None)
    frame: reactive[int] = reactive(0)
    friend: reactive[str] = reactive("Friend")
    friend_status: reactive[str] = reactive("offline")
    online: reactive[bool] = reactive(False)
    ping_ms: reactive[int | None] = reactive(None)

    def render(self) -> Panel:
        """Render the messages panel."""
        table = Table.grid(expand=True)
        table.add_column(ratio=1)

        # Header with app name and friend status
        app_title = f"[bold {OPENCLAW['accent']}]{APP_NAME}[/]"
        status_line = self._format_status_line()
        table.add_row(f"{app_title}\n\n{status_line}\n[{OPENCLAW['border']}]" + "─" * 34 + "[/]")

        # Scroll indicator if scrolled back
        if self.message_scroll:
            table.add_row(
                f"[{OPENCLAW['dim']}]↑ scrolled back {self.message_scroll} message(s) • "
                f"PageDown/End to latest[/]"
            )

        # Display visible messages
        for sender, text, receipt in self._visible_messages():
            sender_style = (
                OPENCLAW["quote"] if sender not in {"You", "System"} else OPENCLAW["accent"]
            )
            if sender == "System":
                sender_style = OPENCLAW["system"]
            table.add_row(
                f"[bold {sender_style}]{sender}:[/]\n"
                f"[{OPENCLAW['text']}]{text}[/] [{OPENCLAW['dim']}]{receipt}[/]"
            )

        # Typing indicator
        if self.typing:
            dots = "." * ((self.frame % 3) + 1)
            table.add_row(
                f"[italic {OPENCLAW['accent_soft']}]{self.friend} is typing{dots}[/]"
            )

        # Command execution spinner
        if self.executing_command:
            spinner = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"[self.frame % 10]
            table.add_row(
                f"[{OPENCLAW['accent']}]{spinner} executing /{self.executing_command}[/]"
            )

        return Panel(
            table,
            border_style=OPENCLAW["border"],
            style=OPENCLAW["text"],
        )

    def _format_status_line(self) -> str:
        """Format the friend status line."""
        if self.friend_status == "online":
            marker = f"[{OPENCLAW['success']}]●[/] Online"
        elif self.friend_status == "idle":
            marker = f"[{OPENCLAW['accent_soft']}]◐[/] Idle"
        else:
            marker = f"[{OPENCLAW['dim']}]○[/] Offline"

        status = f"[{OPENCLAW['text']}]{self.friend}[/] {marker}"

        if self.friend_status == "online" and self.ping_ms is not None:
            status += f" [{OPENCLAW['dim']}]({self.ping_ms} ms)[/]"

        return status

    def _visible_messages(self) -> list[tuple[str, str, str]]:
        """Get the messages visible in the current viewport."""
        window = 40
        end = max(0, len(self.messages) - self.message_scroll)
        start = max(0, end - window)
        return self.messages[start:end]

    @property
    def max_scroll(self) -> int:
        """Maximum scroll offset."""
        return max(0, len(self.messages) - 1)

    def add_message(self, sender: str, text: str, status: str = "") -> None:
        """Add a message to the display."""
        self.messages = [*self.messages, (sender, text, status)]
        self.message_scroll = min(self.message_scroll, self.max_scroll)

    def scroll_messages(self, lines: int) -> None:
        """Scroll messages by a number of lines."""
        self.message_scroll = max(0, min(self.max_scroll, self.message_scroll + lines))

    def tick(self) -> None:
        """Update animation frame."""
        self.frame = (self.frame + 1) % 1_000_000


class CommandsPanel(Static):
    """Displays available commands and keyboard shortcuts."""

    command_help: reactive[list[CommandHelp]] = reactive([], layout=True)

    def render(self) -> Panel:
        """Render the commands panel."""
        table = Table.grid(expand=True)
        table.add_column(justify="left", ratio=1)

        for command in self.command_help:
            table.add_row(
                f"[{OPENCLAW['accent']}]{command.name:<12}[/] "
                f"[{OPENCLAW['dim']}]{command.description}[/]"
            )

        table.add_row("")
        table.add_row(f"[{OPENCLAW['dim']}]Tab autocomplete • ↑/↓ history[/]")
        table.add_row(f"[{OPENCLAW['dim']}]PageUp/PageDown scroll messages[/]")
        table.add_row(f"[{OPENCLAW['dim']}]/commands hide|show|off[/]")

        return Panel(
            table,
            title="Commands",
            border_style=OPENCLAW["border"],
            style=OPENCLAW["text"],
        )

    def set_command_help(self, commands: list[tuple[str, str]]) -> None:
        """Set the command help items."""
        self.command_help = [CommandHelp(name, description) for name, description in commands]


class InputPrompt(Static):
    """Custom input prompt widget."""

    input_buffer: reactive[str] = reactive("", layout=True)

    def render(self) -> Text:
        """Render the input prompt."""
        prompt = Text("\n> ", style=OPENCLAW["accent"])
        prompt.append(self.input_buffer, style=OPENCLAW["text"])
        prompt.append("▌", style=f"bold {OPENCLAW['accent']}")
        return prompt


class ChatContainer(Container):
    """Main chat layout container."""

    class MessageAdded(Message):
        """Posted when a message is added."""

        def __init__(self, sender: str, text: str, status: str = "") -> None:
            self.sender = sender
            self.text = text
            self.status = status
            super().__init__()

    class InputSubmitted(Message):
        """Posted when input is submitted."""

        def __init__(self, text: str) -> None:
            self.text = text
            super().__init__()

    class CommandsVisibilityChanged(Message):
        """Posted when command panel visibility changes."""

        def __init__(self, visible: bool) -> None:
            self.visible = visible
            super().__init__()

    messages: reactive[list[tuple[str, str, str]]] = reactive([], layout=True)
    command_panel_visible: reactive[bool] = reactive(True, layout=True)
    input_buffer: reactive[str] = reactive("")
    message_scroll: reactive[int] = reactive(0)
    typing: reactive[bool] = reactive(False)
    executing_command: reactive[str | None] = reactive(None)
    frame: reactive[int] = reactive(0)
    friend: reactive[str] = reactive("Friend")
    friend_status: reactive[str] = reactive("offline")
    online: reactive[bool] = reactive(False)
    ping_ms: reactive[int | None] = reactive(None)
    self_status: reactive[str] = reactive("online")

    def __init__(self, username: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.username = username
        self.message_display: MessageDisplay | None = None
        self.commands_panel: CommandsPanel | None = None
        self.input_prompt: InputPrompt | None = None

    def compose(self) -> ComposeResult:
        """Compose the chat layout."""
        self.message_display = MessageDisplay(id="message-display")
        self.commands_panel = CommandsPanel(id="commands-panel")
        self.input_prompt = InputPrompt(id="input-prompt")

        with Vertical(id="chat-main"):
            yield self.message_display
            yield self.input_prompt

        yield self.commands_panel

    def watch_messages(self, new_value: list[tuple[str, str, str]]) -> None:
        """Watch messages reactive attribute."""
        if self.message_display:
            self.message_display.messages = new_value

    def watch_command_panel_visible(self, new_value: bool) -> None:
        """Watch command panel visibility."""
        if self.commands_panel:
            self.commands_panel.display = new_value
        self.post_message(self.CommandsVisibilityChanged(new_value))

    def watch_input_buffer(self, new_value: str) -> None:
        """Watch input buffer."""
        if self.input_prompt:
            self.input_prompt.input_buffer = new_value

    def watch_message_scroll(self, new_value: int) -> None:
        """Watch message scroll."""
        if self.message_display:
            self.message_display.message_scroll = new_value

    def watch_typing(self, new_value: bool) -> None:
        """Watch typing indicator."""
        if self.message_display:
            self.message_display.typing = new_value

    def watch_executing_command(self, new_value: str | None) -> None:
        """Watch command execution spinner."""
        if self.message_display:
            self.message_display.executing_command = new_value

    def watch_frame(self, new_value: int) -> None:
        """Watch frame for animations."""
        if self.message_display:
            self.message_display.frame = new_value

    def watch_friend(self, new_value: str) -> None:
        """Watch friend name."""
        if self.message_display:
            self.message_display.friend = new_value

    def watch_friend_status(self, new_value: str) -> None:
        """Watch friend status."""
        if self.message_display:
            self.message_display.friend_status = new_value

    def watch_online(self, new_value: bool) -> None:
        """Watch online status."""
        if self.message_display:
            self.message_display.online = new_value

    def watch_ping_ms(self, new_value: int | None) -> None:
        """Watch ping latency."""
        if self.message_display:
            self.message_display.ping_ms = new_value

    def set_command_help(self, commands: list[tuple[str, str]]) -> None:
        """Set the command help items."""
        if self.commands_panel:
            self.commands_panel.set_command_help(commands)

    def add_message(self, sender: str, text: str, status: str = "") -> None:
        """Add a message."""
        self.messages = [*self.messages, (sender, text, status)]
        if self.message_display:
            self.message_display.add_message(sender, text, status)
        self.message_scroll = min(self.message_scroll, self.max_scroll)

    def scroll_messages(self, lines: int) -> None:
        """Scroll messages."""
        if self.message_display:
            self.message_display.scroll_messages(lines)
            self.message_scroll = self.message_display.message_scroll

    def tick(self) -> None:
        """Update animation frame."""
        self.frame = (self.frame + 1) % 1_000_000
        if self.message_display:
            self.message_display.tick()

    @property
    def max_scroll(self) -> int:
        """Maximum scroll offset."""
        if self.message_display:
            return self.message_display.max_scroll
        return 0


class ChatUI(App):
    """Textual-based chat UI application."""

    CSS = """
    Screen {
        layout: vertical;
        background: $surface;
        color: $text;
    }

    #chat-main {
        height: 1fr;
        width: 1fr;
        border: solid $accent;
    }

    #message-display {
        height: 1fr;
        width: 1fr;
    }

    #input-prompt {
        height: auto;
        width: 100%;
    }

    #commands-panel {
        width: 30;
        height: 1fr;
        border: solid $accent;
        display: block;
    }

    #chat-container {
        height: 1fr;
        width: 1fr;
    }

    Vertical {
        height: 1fr;
        width: 1fr;
    }

    Horizontal {
        height: 1fr;
        width: 1fr;
    }
    """

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit", show=False),
        Binding("pageup", "scroll_up", "Scroll Up", show=False),
        Binding("pagedown", "scroll_down", "Scroll Down", show=False),
        Binding("home", "scroll_home", "Scroll Home", show=False),
        Binding("end", "scroll_end", "Scroll End", show=False),
    ]

    def __init__(self, username: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.username = username
        self.input_history: list[str] = []
        self.history_index: int | None = None
        self.client_callback: Any = None
        self.chat_container: ChatContainer | None = None
        # Pre-store command help
        self._pending_command_help: list[tuple[str, str]] = []

    def compose(self) -> ComposeResult:
        """Compose the app layout."""
        yield Header(show_clock=False)
        self.chat_container = ChatContainer(username=self.username, id="chat-container")
        yield self.chat_container
        yield Footer()

    def on_mount(self) -> None:
        """Set up the app."""
        self.title = "Private Chat"
        # Apply any pending command help
        if self._pending_command_help:
            self.set_command_help(self._pending_command_help)
        # Start the animation loop
        self.set_interval(0.08, self._tick_animation)

    def _tick_animation(self) -> None:
        """Update animation state."""
        if self.chat_container:
            self.chat_container.tick()

    def action_scroll_up(self) -> None:
        """Scroll up (PageUp)."""
        if self.chat_container:
            self.chat_container.scroll_messages(5)

    def action_scroll_down(self) -> None:
        """Scroll down (PageDown)."""
        if self.chat_container:
            self.chat_container.scroll_messages(-5)

    def action_scroll_home(self) -> None:
        """Scroll to home (Home key)."""
        if self.chat_container:
            self.chat_container.scroll_messages(self.chat_container.max_scroll)

    def action_scroll_end(self) -> None:
        """Scroll to end (End key)."""
        if self.chat_container:
            self.chat_container.scroll_messages(-self.chat_container.max_scroll)

    def on_key(self, event: Key) -> None:
        """Handle keyboard input."""
        if not self.client_callback:
            return

        # Handle special keys
        if event.key == "up":
            self.client_callback("restore_history", up=True)
            event.prevent_default()
        elif event.key == "down":
            self.client_callback("restore_history", up=False)
            event.prevent_default()
        elif event.key == "tab":
            self.client_callback("tab_complete")
            event.prevent_default()
        elif event.key in ("backspace", "delete"):
            self.input_buffer = self.input_buffer[:-1]
            self.client_callback("input_changed")
            event.prevent_default()
        elif event.key == "enter":
            self.client_callback("submit_input", text=self.input_buffer)
            self.input_buffer = ""
            event.prevent_default()
        elif event.character and event.character.isprintable():
            self.input_buffer += event.character
            self.client_callback("input_changed")
            event.prevent_default()

    # Delegated properties and methods for compatibility with ChatClient

    @property
    def messages(self) -> list[tuple[str, str, str]]:
        """Get messages."""
        if self.chat_container:
            return self.chat_container.messages
        return []

    @messages.setter
    def messages(self, value: list[tuple[str, str, str]]) -> None:
        """Set messages."""
        if self.chat_container:
            self.chat_container.messages = value

    @property
    def friend(self) -> str:
        """Get friend name."""
        if self.chat_container:
            return self.chat_container.friend
        return "Friend"

    @friend.setter
    def friend(self, value: str) -> None:
        """Set friend name."""
        if self.chat_container:
            self.chat_container.friend = value

    @property
    def friend_status(self) -> str:
        """Get friend status."""
        if self.chat_container:
            return self.chat_container.friend_status
        return "offline"

    @friend_status.setter
    def friend_status(self, value: str) -> None:
        """Set friend status."""
        if self.chat_container:
            self.chat_container.friend_status = value

    @property
    def online(self) -> bool:
        """Get online status."""
        if self.chat_container:
            return self.chat_container.online
        return False

    @online.setter
    def online(self, value: bool) -> None:
        """Set online status."""
        if self.chat_container:
            self.chat_container.online = value

    @property
    def ping_ms(self) -> int | None:
        """Get ping latency."""
        if self.chat_container:
            return self.chat_container.ping_ms
        return None

    @ping_ms.setter
    def ping_ms(self, value: int | None) -> None:
        """Set ping latency."""
        if self.chat_container:
            self.chat_container.ping_ms = value

    @property
    def typing(self) -> bool:
        """Get typing indicator."""
        if self.chat_container:
            return self.chat_container.typing
        return False

    @typing.setter
    def typing(self, value: bool) -> None:
        """Set typing indicator."""
        if self.chat_container:
            self.chat_container.typing = value

    @property
    def input_buffer(self) -> str:
        """Get input buffer."""
        if self.chat_container:
            return self.chat_container.input_buffer
        return ""

    @input_buffer.setter
    def input_buffer(self, value: str) -> None:
        """Set input buffer."""
        if self.chat_container:
            self.chat_container.input_buffer = value

    @property
    def command_panel_visible(self) -> bool:
        """Get command panel visibility."""
        if self.chat_container:
            return self.chat_container.command_panel_visible
        return True

    @command_panel_visible.setter
    def command_panel_visible(self, value: bool) -> None:
        """Set command panel visibility."""
        if self.chat_container:
            self.chat_container.command_panel_visible = value

    @property
    def executing_command(self) -> str | None:
        """Get executing command."""
        if self.chat_container:
            return self.chat_container.executing_command
        return None

    @executing_command.setter
    def executing_command(self, value: str | None) -> None:
        """Set executing command."""
        if self.chat_container:
            self.chat_container.executing_command = value

    @property
    def self_status(self) -> str:
        """Get self status."""
        if self.chat_container:
            return self.chat_container.self_status
        return "online"

    @self_status.setter
    def self_status(self, value: str) -> None:
        """Set self status."""
        if self.chat_container:
            self.chat_container.self_status = value

    @property
    def message_scroll(self) -> int:
        """Get message scroll offset."""
        if self.chat_container:
            return self.chat_container.message_scroll
        return 0

    @message_scroll.setter
    def message_scroll(self, value: int) -> None:
        """Set message scroll offset."""
        if self.chat_container:
            self.chat_container.message_scroll = value

    @property
    def max_scroll(self) -> int:
        """Get maximum scroll offset."""
        if self.chat_container:
            return self.chat_container.max_scroll
        return 0

    def add(self, sender: str, text: str, status: str = "") -> None:
        """Add a message (compatibility method)."""
        if self.chat_container:
            self.chat_container.add_message(sender, text, status)

    def set_command_help(self, commands: list[tuple[str, str]]) -> None:
        """Set command help items."""
        self._pending_command_help = commands
        if self.chat_container:
            self.chat_container.set_command_help(commands)

    def scroll_messages(self, lines: int) -> None:
        """Scroll messages."""
        if self.chat_container:
            self.chat_container.scroll_messages(lines)

    def tick(self) -> None:
        """Tick animation (compatibility method)."""
        if self.chat_container:
            self.chat_container.tick()

    def render(self) -> None:
        """Render the UI (no-op for Textual apps)."""
        pass

    def live(self):
        """Context manager for compatibility (no-op for Textual)."""
        from contextlib import contextmanager

        @contextmanager
        def _live():
            yield self

        return _live()
