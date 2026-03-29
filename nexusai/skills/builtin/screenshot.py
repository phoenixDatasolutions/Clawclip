"""Screenshot Skill — capture screen and active window information."""

from __future__ import annotations

import asyncio
import base64
import logging
from typing import Any

from nexusai.core.types import SkillContext, SkillResult, ToolDefinition

logger = logging.getLogger(__name__)

try:
    import mss
    _MSS_AVAILABLE = True
except ImportError:
    _MSS_AVAILABLE = False

try:
    from PIL import Image
    _PIL_AVAILABLE = True
except ImportError:
    _PIL_AVAILABLE = False


class ScreenshotSkill:
    """Capture screenshots and query active window information."""

    @property
    def name(self) -> str:
        return "screenshot"

    @property
    def description(self) -> str:
        return "Take screenshots and get active window information"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def tools(self) -> list[ToolDefinition]:
        return [
            ToolDefinition(
                name="take_screenshot",
                description="Capture the primary monitor as a base64-encoded PNG",
                parameters={
                    "type": "object",
                    "properties": {
                        "monitor": {"type": "integer", "description": "Monitor index (1 = primary)", "default": 1},
                    },
                },
                required_permissions=["system.screenshot"],
            ),
            ToolDefinition(
                name="get_active_window",
                description="Get the title and dimensions of the currently active window",
                parameters={"type": "object", "properties": {}},
                required_permissions=["system.screenshot"],
            ),
        ]

    @property
    def triggers(self) -> list[str]:
        return ["/screenshot", "/screen"]

    @property
    def required_permissions(self) -> list[str]:
        return ["system.screenshot"]

    async def initialize(self, context: SkillContext) -> None:
        pass

    async def execute(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        context: SkillContext,
    ) -> SkillResult:
        if tool_name == "take_screenshot":
            return await self._take_screenshot(arguments)
        if tool_name == "get_active_window":
            return await self._get_active_window()
        return SkillResult(success=False, output=f"Unknown tool: {tool_name}")

    async def handle_trigger(
        self,
        trigger: str,
        args: str,
        context: SkillContext,
    ) -> SkillResult:
        return await self.execute("take_screenshot", {}, context)

    async def shutdown(self) -> None:
        pass

    # ── private helpers ──────────────────────────────────────────

    async def _take_screenshot(self, args: dict[str, Any]) -> SkillResult:
        if not _MSS_AVAILABLE:
            return SkillResult(success=False, output="mss is not installed", error="missing dependency")
        if not _PIL_AVAILABLE:
            return SkillResult(success=False, output="Pillow is not installed", error="missing dependency")

        monitor_idx = int(args.get("monitor", 1))

        def _capture() -> tuple[str, int, int]:
            import io
            from PIL import Image as PILImage

            with mss.mss() as sct:
                monitors = sct.monitors
                if monitor_idx >= len(monitors):
                    raise ValueError(f"Monitor {monitor_idx} not found (available: 0-{len(monitors)-1})")
                monitor = monitors[monitor_idx]
                shot = sct.grab(monitor)
                img = PILImage.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
                buf = io.BytesIO()
                img.save(buf, format="PNG", optimize=True)
                png_bytes = buf.getvalue()
                b64 = base64.b64encode(png_bytes).decode("ascii")
                return b64, shot.size[0], shot.size[1]

        try:
            b64, width, height = await asyncio.get_event_loop().run_in_executor(None, _capture)
            return SkillResult(
                success=True,
                output=f"Screenshot captured: {width}x{height} pixels",
                artifacts=[{"image_base64": b64, "width": width, "height": height}],
            )
        except Exception as e:
            return SkillResult(success=False, output=str(e), error=str(e))

    async def _get_active_window(self) -> SkillResult:
        def _get_window() -> str:
            import platform
            system = platform.system()

            if system == "Windows":
                try:
                    import ctypes
                    hwnd = ctypes.windll.user32.GetForegroundWindow()
                    length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
                    buf = ctypes.create_unicode_buffer(length + 1)
                    ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
                    title = buf.value or "(no title)"

                    rect = ctypes.wintypes.RECT()
                    ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
                    width = rect.right - rect.left
                    height = rect.bottom - rect.top
                    return f"Active window: '{title}' ({width}x{height})"
                except Exception as e:
                    return f"Could not get active window: {e}"

            elif system == "Darwin":
                try:
                    import subprocess
                    result = subprocess.run(
                        ["osascript", "-e", 'tell application "System Events" to get name of first application process whose frontmost is true'],
                        capture_output=True, text=True, timeout=5,
                    )
                    return f"Active application: {result.stdout.strip()}"
                except Exception as e:
                    return f"Could not get active window: {e}"

            else:
                return "Active window detection not supported on this platform"

        try:
            output = await asyncio.get_event_loop().run_in_executor(None, _get_window)
            return SkillResult(success=True, output=output)
        except Exception as e:
            return SkillResult(success=False, output=str(e), error=str(e))


def create_skill(config: dict) -> ScreenshotSkill:
    return ScreenshotSkill()
