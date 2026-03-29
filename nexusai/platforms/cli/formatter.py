"""CLI output formatter — Rich markup for terminal rendering."""

from __future__ import annotations


class CLIFormatter:
    """``OutputFormatter`` implementation for the CLI / terminal platform.

    Uses `Rich <https://rich.readthedocs.io>`_ markup so text is rendered
    with colour and styling in the terminal.  When Rich is not installed the
    markup tags are still emitted; they are human-readable even as plain text.

    Rich markup reference:
    * ``[bold]…[/bold]``
    * ``[italic]…[/italic]``
    * ``[code]…[/code]``
    * Code blocks use ``[green]`` for the language label and
      a ``[dim]`` fence to visually delimit the block.
    """

    max_message_length: int = 100_000

    # ── OutputFormatter protocol ──────────────────────────────────

    def bold(self, text: str) -> str:
        return f"[bold]{text}[/bold]"

    def italic(self, text: str) -> str:
        return f"[italic]{text}[/italic]"

    def code(self, text: str) -> str:
        return f"[code]{text}[/code]"

    def code_block(self, text: str, language: str = "") -> str:
        lang_label = f"[green]{language}[/green]" if language else ""
        fence = "[dim]```[/dim]"
        return f"{fence}{lang_label}\n{text}\n{fence}"

    def link(self, text: str, url: str) -> str:
        return f"[link={url}]{text}[/link]"

    def escape(self, text: str) -> str:
        """Escape Rich markup brackets so they print literally."""
        return str(text).replace("[", r"\[")
