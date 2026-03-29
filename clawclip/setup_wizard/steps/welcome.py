"""ClawClip Setup Wizard — Welcome step with branded display."""

from __future__ import annotations

from rich.console import Console
from rich.text import Text
from rich.panel import Panel
from rich import box

console = Console()

LOGO = r"""
 ██████╗██╗      █████╗ ██╗    ██╗ ██████╗██╗     ██╗██████╗
██╔════╝██║     ██╔══██╗██║    ██║██╔════╝██║     ██║██╔══██╗
██║     ██║     ███████║██║ █╗ ██║██║     ██║     ██║██████╔╝
██║     ██║     ██╔══██║██║███╗██║██║     ██║     ██║██╔═══╝
╚██████╗███████╗██║  ██║╚███╔███╔╝╚██████╗███████╗██║██║
 ╚═════╝╚══════╝╚═╝  ╚═╝ ╚══╝╚══╝  ╚═════╝╚══════╝╚═╝╚═╝     """


def show_welcome() -> None:
    """Display the ClawClip branded welcome screen."""
    console.print()
    console.print(LOGO, style="bold red")
    console.print("  Multi-Agent AI Platform", style="red")
    console.print("  ─────────────────────────────────────────────────────────", style="dim red")
    console.print()
