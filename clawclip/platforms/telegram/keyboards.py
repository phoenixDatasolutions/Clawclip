"""Telegram inline keyboard builders for common UI patterns."""

from __future__ import annotations

from typing import Any

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def main_menu_keyboard() -> InlineKeyboardMarkup:
    """Main menu with common actions grouped into rows."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Chat with AI", callback_data="cmd:chat"),
                InlineKeyboardButton(text="Sessions", callback_data="cmd:sessions"),
            ],
            [
                InlineKeyboardButton(text="Shell (Bash)", callback_data="cmd:sh"),
                InlineKeyboardButton(text="PowerShell", callback_data="cmd:ps"),
            ],
            [
                InlineKeyboardButton(text="Files", callback_data="cmd:ls"),
                InlineKeyboardButton(text="Screenshot", callback_data="cmd:screenshot"),
            ],
            [
                InlineKeyboardButton(text="System Info", callback_data="cmd:sysinfo"),
                InlineKeyboardButton(text="Git", callback_data="cmd:git"),
            ],
            [
                InlineKeyboardButton(text="Cost", callback_data="cmd:cost"),
                InlineKeyboardButton(text="Switch Model", callback_data="cmd:model"),
            ],
        ]
    )


def model_selector_keyboard(current_model: str | None = None) -> InlineKeyboardMarkup:
    """Model selection buttons — highlights the currently active model."""
    models = [
        ("Sonnet", "sonnet"),
        ("Opus", "opus"),
        ("Haiku", "haiku"),
    ]
    buttons: list[InlineKeyboardButton] = []
    for label, model_id in models:
        display = f">> {label} <<" if model_id == current_model else label
        buttons.append(
            InlineKeyboardButton(text=display, callback_data=f"model:{model_id}")
        )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            buttons,
            [InlineKeyboardButton(text="<< Back", callback_data="cmd:menu")],
        ]
    )


def session_keyboard(sessions: list[dict[str, Any]]) -> InlineKeyboardMarkup:
    """List sessions with resume buttons.

    Each ``session`` dict should have at minimum:
    - ``id``: unique session identifier
    - ``name``: display name (falls back to truncated id)
    - ``is_active`` (optional): boolean flag
    - ``cost`` (optional): float cost in USD
    """
    rows: list[list[InlineKeyboardButton]] = []
    for s in sessions:
        label = s.get("name") or str(s["id"])[:8]
        if s.get("is_active"):
            label += " [active]"
        cost = s.get("cost")
        if cost:
            label += f" ${cost:.2f}"
        rows.append([
            InlineKeyboardButton(
                text=label,
                callback_data=f"session:{s['id']}",
            )
        ])
    rows.append([
        InlineKeyboardButton(text="+ New Session", callback_data="session:new")
    ])
    rows.append([
        InlineKeyboardButton(text="<< Back", callback_data="cmd:menu")
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def confirm_keyboard(action_id: str) -> InlineKeyboardMarkup:
    """Yes / No confirmation keyboard for a specific action.

    The ``action_id`` is embedded in the callback data so the handler
    can look up what is being confirmed.
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Yes", callback_data=f"confirm:{action_id}:yes"
                ),
                InlineKeyboardButton(
                    text="No", callback_data=f"confirm:{action_id}:no"
                ),
            ],
        ]
    )


def pagination_keyboard(page: int, total_pages: int) -> InlineKeyboardMarkup:
    """Prev / Next pagination with page indicator.

    Args:
        page: Current page number (0-indexed).
        total_pages: Total number of pages.
    """
    buttons: list[InlineKeyboardButton] = []

    if page > 0:
        buttons.append(
            InlineKeyboardButton(text="<< Prev", callback_data=f"page:{page - 1}")
        )

    buttons.append(
        InlineKeyboardButton(
            text=f"{page + 1}/{total_pages}",
            callback_data="noop",
        )
    )

    if page < total_pages - 1:
        buttons.append(
            InlineKeyboardButton(text="Next >>", callback_data=f"page:{page + 1}")
        )

    return InlineKeyboardMarkup(
        inline_keyboard=[
            buttons,
            [InlineKeyboardButton(text="<< Back", callback_data="cmd:menu")],
        ]
    )
