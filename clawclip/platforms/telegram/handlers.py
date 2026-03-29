"""Telegram aiogram 3.x router — command handlers and FSM states.

All handlers delegate real work to the adapter's registered callbacks
(which route into the ClawClip core), rather than importing core modules
directly.  This keeps the platform layer thin.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from clawclip.core.types import (
    FileAttachment,
    IncomingMessage,
    PlatformUser,
)
from clawclip.platforms.telegram.formatter import TelegramFormatter
from clawclip.platforms.telegram.keyboards import (
    main_menu_keyboard,
    model_selector_keyboard,
    session_keyboard,
)

if TYPE_CHECKING:
    from clawclip.platforms.telegram.adapter import TelegramAdapter

logger = logging.getLogger(__name__)

# ── FSM States ────────────────────────────────────────────────────

class ChatMode(StatesGroup):
    """User is in interactive chat mode — all free text goes to the agent."""
    active = State()


# ── Router factory ────────────────────────────────────────────────

def build_router(adapter: TelegramAdapter) -> Router:
    """Create and return an aiogram ``Router`` wired to the given adapter.

    The ``adapter`` reference is captured in closures so handlers can
    dispatch to registered callbacks and use adapter methods for
    sending/streaming.
    """
    router = Router(name="telegram_main")
    fmt = TelegramFormatter()

    # ── Helper: build IncomingMessage from aiogram Message ─────

    def _to_incoming(message: Message, text_override: str | None = None) -> IncomingMessage:
        """Convert an aiogram ``Message`` to a ClawClip ``IncomingMessage``."""
        user = message.from_user
        return IncomingMessage(
            platform="telegram",
            channel_id=str(message.chat.id),
            message_id=str(message.message_id),
            user=PlatformUser(
                platform="telegram",
                platform_user_id=str(user.id) if user else "0",
                username=user.username if user else None,
                display_name=user.full_name if user else None,
            ),
            text=text_override if text_override is not None else (message.text or ""),
            raw={"aiogram_message": message},
        )

    # ── /start ────────────────────────────────────────────────────

    @router.message(Command("start"))
    async def cmd_start(message: Message) -> None:
        await message.answer(
            f"{fmt.bold('Welcome to ClawClip!')}\n\n"
            "Your intelligent assistant across platforms.\n"
            "Use the menu below or type /help for all commands.",
            parse_mode="HTML",
            reply_markup=main_menu_keyboard(),
        )

    # ── /help ─────────────────────────────────────────────────────

    @router.message(Command("help"))
    async def cmd_help(message: Message) -> None:
        help_text = (
            f"{fmt.bold('ClawClip Commands')}\n\n"
            f"{fmt.bold('AI:')}\n"
            "/ask &lt;prompt&gt; -- One-shot AI query\n"
            "/chat -- Toggle chat mode\n"
            "/sessions -- List sessions\n"
            "/newsession [name] -- Create session\n"
            "/resume &lt;id&gt; -- Resume session\n"
            "/model &lt;name&gt; -- Switch model\n"
            "/cost -- Usage cost summary\n\n"
            f"{fmt.bold('Shell:')}\n"
            "/sh &lt;cmd&gt; -- Bash command\n"
            "/ps &lt;cmd&gt; -- PowerShell command\n\n"
            f"{fmt.bold('Files:')}\n"
            "/ls [path] -- List directory\n"
            "/cat &lt;file&gt; -- Read file\n\n"
            f"{fmt.bold('System:')}\n"
            "/sysinfo -- System information\n"
            "/screenshot -- Desktop capture\n\n"
            f"{fmt.bold('Git:')}\n"
            "/git &lt;subcommand&gt; -- Git operations\n\n"
            "/menu -- Main menu"
        )
        await message.answer(help_text, parse_mode="HTML")

    # ── /menu ─────────────────────────────────────────────────────

    @router.message(Command("menu"))
    async def cmd_menu(message: Message) -> None:
        await message.answer("Main Menu:", reply_markup=main_menu_keyboard())

    # ── /ask <prompt> ─────────────────────────────────────────────

    @router.message(Command("ask"))
    async def cmd_ask(message: Message, command: CommandObject) -> None:
        prompt = command.args
        if not prompt:
            await message.answer("Usage: /ask &lt;your prompt&gt;", parse_mode="HTML")
            return
        incoming = _to_incoming(message, text_override=f"/ask {prompt}")
        await adapter._dispatch_message(incoming)

    # ── /chat — toggle chat mode ──────────────────────────────────

    @router.message(Command("chat"))
    async def cmd_chat(message: Message, state: FSMContext) -> None:
        current = await state.get_state()
        if current == ChatMode.active:
            await state.clear()
            await message.answer(
                "Chat mode OFF. Messages will no longer be sent to the AI."
            )
            return
        await state.set_state(ChatMode.active)
        await message.answer(
            "Chat mode ON.\n"
            "Send any message to talk to the AI.\n"
            "Type /chat again to exit."
        )
        incoming = _to_incoming(message, text_override="/chat")
        await adapter._dispatch_message(incoming)

    # ── Free text in chat mode ────────────────────────────────────

    @router.message(ChatMode.active, F.text)
    async def handle_chat_text(message: Message) -> None:
        incoming = _to_incoming(message)
        await adapter._dispatch_message(incoming)

    # ── /sh <command> ─────────────────────────────────────────────

    @router.message(Command("sh"))
    async def cmd_sh(message: Message, command: CommandObject) -> None:
        cmd_text = command.args
        if not cmd_text:
            await message.answer("Usage: /sh &lt;command&gt;", parse_mode="HTML")
            return
        incoming = _to_incoming(message, text_override=f"/sh {cmd_text}")
        await adapter._dispatch_message(incoming)

    # ── /ps <command> ─────────────────────────────────────────────

    @router.message(Command("ps"))
    async def cmd_ps(message: Message, command: CommandObject) -> None:
        cmd_text = command.args
        if not cmd_text:
            await message.answer("Usage: /ps &lt;command&gt;", parse_mode="HTML")
            return
        incoming = _to_incoming(message, text_override=f"/ps {cmd_text}")
        await adapter._dispatch_message(incoming)

    # ── /ls [path] ────────────────────────────────────────────────

    @router.message(Command("ls"))
    async def cmd_ls(message: Message, command: CommandObject) -> None:
        path = command.args or ""
        incoming = _to_incoming(message, text_override=f"/ls {path}".strip())
        await adapter._dispatch_message(incoming)

    # ── /cat <file> ───────────────────────────────────────────────

    @router.message(Command("cat"))
    async def cmd_cat(message: Message, command: CommandObject) -> None:
        path = command.args
        if not path:
            await message.answer("Usage: /cat &lt;file&gt;", parse_mode="HTML")
            return
        incoming = _to_incoming(message, text_override=f"/cat {path}")
        await adapter._dispatch_message(incoming)

    # ── /sysinfo ──────────────────────────────────────────────────

    @router.message(Command("sysinfo"))
    async def cmd_sysinfo(message: Message) -> None:
        incoming = _to_incoming(message, text_override="/sysinfo")
        await adapter._dispatch_message(incoming)

    # ── /screenshot ───────────────────────────────────────────────

    @router.message(Command("screenshot"))
    async def cmd_screenshot(message: Message) -> None:
        incoming = _to_incoming(message, text_override="/screenshot")
        await adapter._dispatch_message(incoming)

    # ── /git <subcommand> ─────────────────────────────────────────

    @router.message(Command("git"))
    async def cmd_git(message: Message, command: CommandObject) -> None:
        subcmd = command.args or ""
        if not subcmd:
            await message.answer(
                "Usage: /git &lt;subcommand&gt;\n"
                "Examples: /git status, /git log --oneline -10",
                parse_mode="HTML",
            )
            return
        incoming = _to_incoming(message, text_override=f"/git {subcmd}")
        await adapter._dispatch_message(incoming)

    # ── /sessions ─────────────────────────────────────────────────

    @router.message(Command("sessions"))
    async def cmd_sessions(message: Message) -> None:
        incoming = _to_incoming(message, text_override="/sessions")
        await adapter._dispatch_message(incoming)

    # ── /newsession [name] ────────────────────────────────────────

    @router.message(Command("newsession"))
    async def cmd_newsession(message: Message, command: CommandObject) -> None:
        name = command.args or ""
        incoming = _to_incoming(message, text_override=f"/newsession {name}".strip())
        await adapter._dispatch_message(incoming)

    # ── /resume <id> ──────────────────────────────────────────────

    @router.message(Command("resume"))
    async def cmd_resume(message: Message, command: CommandObject) -> None:
        session_id = command.args
        if not session_id:
            await message.answer("Usage: /resume &lt;session_id&gt;", parse_mode="HTML")
            return
        incoming = _to_incoming(message, text_override=f"/resume {session_id}")
        await adapter._dispatch_message(incoming)

    # ── /model <name> ─────────────────────────────────────────────

    @router.message(Command("model"))
    async def cmd_model(message: Message, command: CommandObject) -> None:
        model_name = command.args
        if not model_name:
            await message.answer(
                "Pick a model:", reply_markup=model_selector_keyboard()
            )
            return
        incoming = _to_incoming(message, text_override=f"/model {model_name}")
        await adapter._dispatch_message(incoming)

    # ── /cost ─────────────────────────────────────────────────────

    @router.message(Command("cost"))
    async def cmd_cost(message: Message) -> None:
        incoming = _to_incoming(message, text_override="/cost")
        await adapter._dispatch_message(incoming)

    # ── Callback query handler (inline button clicks) ─────────────

    @router.callback_query()
    async def handle_callback(callback: CallbackQuery) -> None:
        data = callback.data or ""
        await callback.answer()

        # Some buttons are handled locally (menu navigation)
        if data == "cmd:menu":
            await callback.message.edit_text(
                "Main Menu:", reply_markup=main_menu_keyboard()
            )
            return

        if data == "cmd:model":
            await callback.message.edit_text(
                "Select a model:", reply_markup=model_selector_keyboard()
            )
            return

        if data == "noop":
            return

        if data == "dismiss":
            try:
                await callback.message.delete()
            except Exception:
                pass
            return

        # Everything else is dispatched to registered button callbacks
        user = callback.from_user
        platform_user = PlatformUser(
            platform="telegram",
            platform_user_id=str(user.id) if user else "0",
            username=user.username if user else None,
            display_name=user.full_name if user else None,
        )
        message_id = str(callback.message.message_id) if callback.message else ""
        await adapter._dispatch_button_click(data, message_id, platform_user)

    return router
