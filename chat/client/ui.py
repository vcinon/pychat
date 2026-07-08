"""Rich terminal UI."""

from __future__ import annotations

from dataclasses import dataclass, field

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.layout import Layout

from chat.shared.constants import APP_NAME

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
    name: str
    description: str


@dataclass
class ChatUI:
    username: str
    friend: str = "Friend"
    console: Console = field(default_factory=Console)
    messages: list[tuple[str, str, str]] = field(default_factory=list)
    command_help: list[CommandHelp] = field(default_factory=list)
    online: bool = False
    friend_status: str = "offline"
    self_status: str = "online"
    ping_ms: int | None = None
    typing: bool = False
    input_buffer: str = ""
    command_panel_visible: bool = True
    executing_command: str | None = None
    frame: int = 0

    def add(self, sender: str, text: str, status: str = "") -> None:
        self.messages.append((sender, text, status))

    def set_command_help(self, commands: list[tuple[str, str]]) -> None:
        self.command_help = [CommandHelp(name, description) for name, description in commands]

    def tick(self) -> None:
        self.frame = (self.frame + 1) % 1_000_000

    def _status_line(self) -> str:
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

    def _chat_panel(self) -> Panel:
        table = Table.grid(expand=True)
        table.add_column(ratio=1)
        table.add_row(f"[bold {OPENCLAW['accent']}]{APP_NAME}[/]\n\n{self._status_line()}\n[{OPENCLAW['border']}]" + "─" * 34 + "[/]")
        for sender, text, receipt in self.messages[-100:]:
            sender_style = OPENCLAW["quote"] if sender not in {"You", "System"} else OPENCLAW["accent"]
            if sender == "System":
                sender_style = OPENCLAW["system"]
            table.add_row(f"[bold {sender_style}]{sender}:[/]\n[{OPENCLAW['text']}]{text}[/] [{OPENCLAW['dim']}]{receipt}[/]")
        if self.typing:
            dots = "." * ((self.frame % 3) + 1)
            table.add_row(f"[italic {OPENCLAW['accent_soft']}]{self.friend} is typing{dots}[/]")
        if self.executing_command:
            spinner = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"[self.frame % 10]
            table.add_row(f"[{OPENCLAW['accent']}]{spinner} executing /{self.executing_command}[/]")
        prompt = Text("\n> ", style=OPENCLAW["accent"])
        prompt.append(self.input_buffer, style=OPENCLAW["text"])
        prompt.append("▌", style=f"bold {OPENCLAW['accent']}")
        table.add_row(prompt)
        return Panel(table, border_style=OPENCLAW["border"], style=OPENCLAW["text"])

    def _commands_panel(self) -> Panel:
        table = Table.grid(expand=True)
        table.add_column(justify="left", ratio=1)
        for command in self.command_help:
            table.add_row(f"[{OPENCLAW['accent']}]{command.name:<12}[/] [{OPENCLAW['dim']}]{command.description}[/]")
        table.add_row("")
        table.add_row(f"[{OPENCLAW['dim']}]Tab autocomplete • ↑/↓ history[/]")
        table.add_row(f"[{OPENCLAW['dim']}]/commands hide|show|off[/]")
        return Panel(table, title="Commands", border_style=OPENCLAW["border"], style=OPENCLAW["text"])

    def render(self) -> Panel | Layout:
        chat_panel = self._chat_panel()
        if not self.command_panel_visible:
            return chat_panel
        layout = Layout()
        layout.split_row(Layout(chat_panel, ratio=3), Layout(self._commands_panel(), ratio=1, minimum_size=30))
        return layout

    def live(self) -> Live:
        return Live(
            self.render(),
            console=self.console,
            refresh_per_second=16,
            screen=True,
            redirect_stdout=False,
            redirect_stderr=False,
        )
