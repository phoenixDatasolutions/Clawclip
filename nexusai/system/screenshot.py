"""Desktop screenshot capture using mss."""

from __future__ import annotations

import asyncio
import io

import mss
from PIL import Image


def _capture_screenshot() -> bytes:
    """Synchronous screenshot capture. Returns PNG bytes."""
    with mss.mss() as sct:
        # Capture the primary monitor
        monitor = sct.monitors[1]  # 1 = primary monitor (0 = all monitors combined)
        screenshot = sct.grab(monitor)

        # Convert BGRA to RGB using Pillow
        img = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")

        # Compress to PNG
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return buf.getvalue()


async def take_screenshot() -> bytes:
    """Async wrapper for screenshot capture. Returns PNG bytes."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _capture_screenshot)
