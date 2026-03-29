"""Discord UI views — Button components using discord.py's ui framework."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Awaitable, Callable

try:
    import discord
    import discord.ui

    _DISCORD_AVAILABLE = True
except ImportError:
    _DISCORD_AVAILABLE = False

if TYPE_CHECKING:
    from clawclip.core.types import ButtonAction

logger = logging.getLogger(__name__)


if _DISCORD_AVAILABLE:

    class ButtonView(discord.ui.View):
        """A discord.py View populated from ClawClip ``ButtonAction`` rows.

        Each ``ButtonAction`` in each row becomes a ``discord.ui.Button``.
        When pressed, the registered ``callback`` is called with the button's
        ``callback_data`` and the pressing user's id.

        Args:
            buttons:  Row-major list of ``ButtonAction`` objects.
            callback: ``async def handler(callback_data: str, user_id: str)``
            timeout:  Seconds before the view stops listening (default 180).
        """

        def __init__(
            self,
            buttons: list[list[ButtonAction]],
            callback: Callable[[str, str], Awaitable[None]],
            *,
            timeout: float = 180.0,
        ) -> None:
            super().__init__(timeout=timeout)
            self._action_callback = callback

            for row_idx, row in enumerate(buttons):
                for btn in row:
                    button = _make_button(btn, row_idx, callback)
                    self.add_item(button)

    def _make_button(
        btn: ButtonAction,
        row: int,
        callback: Callable[[str, str], Awaitable[None]],
    ) -> discord.ui.Button:
        """Build a single ``discord.ui.Button`` from a ``ButtonAction``."""

        class _Btn(discord.ui.Button):
            def __init__(self) -> None:
                super().__init__(
                    label=btn.text,
                    url=btn.url if btn.url else None,
                    style=discord.ButtonStyle.link if btn.url else discord.ButtonStyle.primary,
                    custom_id=None if btn.url else btn.callback_data,
                    row=row,
                )
                self._callback_data = btn.callback_data
                self._action_callback = callback

            async def callback(self, interaction: discord.Interaction) -> None:
                await interaction.response.defer()
                user_id = str(interaction.user.id)
                try:
                    await self._action_callback(self._callback_data, user_id)
                except Exception:
                    logger.exception("ButtonView callback raised an exception")

        return _Btn()

else:
    # Stub so imports don't blow up when discord.py is absent.

    class ButtonView:  # type: ignore[no-redef]
        """Stub ButtonView — discord.py not installed."""

        def __init__(self, *args, **kwargs) -> None:
            raise ImportError(
                "discord.py is not installed. "
                "Install it with: pip install discord.py"
            )
