"""Rich terminal UI."""

from __future__ import annotations

from dataclasses import dataclass, field

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table

from chat.shared.constants import APP_NAME


@dataclass
class ChatUI:
    username: str
    friend: str = "Friend"
    console: Console = field(default_factory=Console)
    messages: list[tuple[str, str, str]] = field(default_factory=list)
    online: bool = False
    ping_ms: int | None = None
    typing: bool = False

    def add(self, sender: str, text: str, status: str = "") -> None:
        self.messages.append((sender, text, status))

    def render(self) -> Panel:
        table = Table.grid(expand=True)
        table.add_column(ratio=1)
        status = f"{self.friend} {'● Online' if self.online else '○ Offline'}"
        if self.online and self.ping_ms is not None:
            status += f" ({self.ping_ms} ms)"
        table.add_row(f"[bold]{APP_NAME}[/bold]\n\n{status}\n" + "─" * 34)
        for sender, text, receipt in self.messages[-100:]:
            table.add_row(f"[bold]{sender}:[/bold]\n{text} {receipt}")
        if self.typing:
            table.add_row(f"[italic]{self.friend} is typing...[/italic]")
        table.add_row("\n> _")
        return Panel(table)

    def live(self) -> Live:
        return Live(self.render(), console=self.console, refresh_per_second=8, screen=False)
