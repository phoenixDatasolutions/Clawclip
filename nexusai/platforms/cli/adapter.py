"""CLI platform adapter — stdin/stdout based platform with Rich terminal output."""

from __future__ import annotations

import asyncio
import logging
import sys
import time
import uuid
from collections.abc import AsyncGenerator

try:
    from rich.console import Console
    from rich.live import Live
    from rich.markup import escape as rich_escape
    from rich.text import Text

    _RICH_AVAILABLE = True
except ImportError:
    _RICH_AVAILABLE = False

from nexusai.core.enums import PlatformCapability
from nexusai.core.events import EventBus
from nexusai.core.types import (
    ButtonAction,
    FileAttachment,
    IncomingMessage,
    OutgoingMessage,
    PlatformUser,
    StreamChunk,
)
from nexusai.platforms.base import BasePlatformAdapter
from nexusai.platforms.cli.formatter import CLIFormatter

logger = logging.getLogger(__name__)

# Fixed local user for stdin
_CLI_USER = PlatformUser(
    platform="cli",
    platform_user_id="local",
    username="user",
    display_name="Local User",
)

_CHANNEL_ID = "cli"


class CLIAdapter(BasePlatformAdapter):
    """``PlatformAdapter`` implementation reading from stdin and writing to stdout.

    Uses `Rich <https://rich.readthedocs.io>`_ for styled terminal output when
    available, falling back to plain ``print`` otherwise.  Streaming responses
    use ``rich.live.Live`` to update a single line in-place.

    Args:
        event_bus: NexusAI event bus.
        prompt:    Input prompt string shown to the user (default ``"> "``).

    Usage::

        adapter = CLIAdapter(event_bus=bus)
        adapter.on_message(my_handler)
        await adapter.start()
    """

    CAPABILITIES = (
        PlatformCapability.TEXT
        | PlatformCapability.STREAMING_EDITS
        | PlatformCapability.RICH_FORMATTING
    )

    def __init__(
        self,
        event_bus: EventBus,
        *,
        prompt: str = "> ",
    ) -> None:
        super().__init__(
            platform_name="cli",
            event_bus=event_bus,
            stream_edit_interval=0.1,
            max_message_length=100_000,
        )
        self._prompt = prompt
        self._formatter = CLIFormatter()
        self._stdin_task: asyncio.Task[None] | None = None
        self._running = False

        if _RICH_AVAILABLE:
            self._console = Console(highlight=False)
        else:
            self._console = None  # type: ignore[assignment]

    # ── PlatformAdapter protocol properties ───────────────────────

    @property
    def name(self) -> str:
        return "cli"

    @property
    def capabilities(self) -> int:
        return int(self.CAPABILITIES.value)

    # ── Lifecycle ─────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the stdin reader loop."""
        logger.info("Starting CLI adapter...")
        self._running = True
        self._start_queue_consumer()
        self._stdin_task = asyncio.create_task(self._read_stdin())
        logger.info("CLI adapter started — reading from stdin")

    async def stop(self) -> None:
        """Stop the stdin reader."""
        logger.info("Stopping CLI adapter...")
        self._running = False
        self._stop_queue_consumer()

        if self._stdin_task and not self._stdin_task.done():
            self._stdin_task.cancel()
            try:
                await self._stdin_task
            except asyncio.CancelledError:
                pass

        logger.info("CLI adapter stopped")

    # ── stdin reader ──────────────────────────────────────────────

    async def _read_stdin(self) -> None:
        """Continuously read lines from stdin and dispatch them as messages."""
        loop = asyncio.get_event_loop()

        while self._running:
            try:
                # Run blocking readline in a thread executor so we don't block the loop
                line: str = await loop.run_in_executor(None, sys.stdin.readline)
            except (EOFError, KeyboardInterrupt):
                logger.info("CLI stdin closed")
                break
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("CLI stdin read error")
                break

            if not line:
                # EOF
                break

            text = line.rstrip("\n")
            if not text:
                continue

            incoming = IncomingMessage(
                platform="cli",
                channel_id=_CHANNEL_ID,
                message_id=str(uuid.uuid4()),
                user=_CLI_USER,
                text=text,
            )
            await self._dispatch_message(incoming)

    # ── send_message ──────────────────────────────────────────────

    async def send_message(
        self,
        channel_id: str,
        message: OutgoingMessage,
    ) -> str:
        """Print a message to stdout with Rich formatting.

        Returns a generated message ID with a timestamp suffix.
        """
        message_id = f"cli-{time.time_ns()}"
        text = message.text

        if len(text) > self._formatter.max_message_length:
            text = text[: self._formatter.max_message_length]

        if self._console is not None:
            self._console.print(text)
        else:
            print(text)  # noqa: T201

        # If the message carries buttons, print them below the text
        if message.buttons:
            self._print_buttons(message.buttons)

        return message_id

    # ── edit_message ──────────────────────────────────────────────

    async def edit_message(
        self,
        channel_id: str,
        message_id: str,
        message: OutgoingMessage,
    ) -> None:
        """CLI does not support in-place edits outside of streaming context.

        This is a no-op outside of ``stream_response``.  Actual streaming
        edits are handled inline in that method.
        """

    # ── delete_message ────────────────────────────────────────────

    async def delete_message(
        self,
        channel_id: str,
        message_id: str,
    ) -> None:
        """CLI does not support message deletion — no-op."""

    # ── send_file ─────────────────────────────────────────────────

    async def send_file(
        self,
        channel_id: str,
        file: FileAttachment,
        caption: str | None = None,
    ) -> str:
        """Print a file notice to the terminal.

        The file content is not printed; only the filename and size are shown.
        """
        size_kb = (file.size or len(file.content or b"")) / 1024
        notice = f"[File: {file.filename}  {size_kb:.1f} KB]"
        if caption:
            notice = f"{caption}\n{notice}"

        message_id = f"cli-{time.time_ns()}"
        if self._console is not None:
            self._console.print(notice)
        else:
            print(notice)  # noqa: T201
        return message_id

    # ── send_buttons ──────────────────────────────────────────────

    async def send_buttons(
        self,
        channel_id: str,
        text: str,
        buttons: list[list[ButtonAction]],
    ) -> str:
        """Print a message followed by numbered button options."""
        msg = OutgoingMessage(text=text, buttons=buttons)
        return await self.send_message(channel_id, msg)

    # ── stream_response ───────────────────────────────────────────

    async def stream_response(
        self,
        channel_id: str,
        chunks: AsyncGenerator[StreamChunk, None],
        initial_text: str = "Processing...",
    ) -> str:
        """Stream a response to the terminal using Rich Live.

        When Rich is available: uses ``rich.live.Live`` to update the
        displayed text in-place as chunks arrive.

        When Rich is not available: prints each chunk flush-separated to
        stdout, finishing with a newline.

        Returns a generated message ID.
        """
        message_id = f"cli-{time.time_ns()}"
        buffer: list[str] = []

        if _RICH_AVAILABLE and self._console is not None:
            with Live(
                initial_text,
                console=self._console,
                refresh_per_second=10,
            ) as live:
                async for chunk in chunks:
                    if chunk.is_final:
                        if chunk.text:
                            buffer.append(chunk.text)
                        break

                    if chunk.text:
                        buffer.append(chunk.text)
                        live.update("".join(buffer))

                # Final render
                full_text = "".join(buffer)
                if full_text:
                    live.update(full_text)
        else:
            # Fallback: plain print with carriage-return trick
            print(initial_text, end="\r", flush=True)  # noqa: T201
            async for chunk in chunks:
                if chunk.is_final:
                    if chunk.text:
                        buffer.append(chunk.text)
                    break
                if chunk.text:
                    buffer.append(chunk.text)
                    print("".join(buffer), end="\r", flush=True)  # noqa: T201

            print("".join(buffer))  # noqa: T201 — final newline

        return message_id

    # ── get_user_info ─────────────────────────────────────────────

    async def get_user_info(self, platform_user_id: str) -> PlatformUser:
        """Return the fixed local CLI user."""
        return _CLI_USER

    # ── Internal helpers ──────────────────────────────────────────

    def _print_buttons(self, buttons: list[list[ButtonAction]]) -> None:
        """Print button options as a numbered list."""
        lines = []
        n = 1
        for row in buttons:
            for btn in row:
                lines.append(f"  [{n}] {btn.text}")
                n += 1

        block = "\n".join(lines)
        if self._console is not None:
            self._console.print(block)
        else:
            print(block)  # noqa: T201
