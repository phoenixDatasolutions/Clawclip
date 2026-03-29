"""Pre-built sandbox image management — pull, list, and check Docker images."""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)

PREBUILT_IMAGES: list[str] = [
    "python:3.12-slim",
    "node:20-slim",
    "alpine:3.20",
]


class ImageManager:
    """Manages Docker images for sandbox containers.

    Provides helpers to pull, list, and check availability of images.
    All operations use subprocess ``docker`` CLI calls; no SDK needed.
    """

    # ── Public API ───────────────────────────────────────────────

    async def pull_image(self, image: str) -> bool:
        """Pull a Docker image.  Returns True on success."""
        logger.info("Pulling image: %s", image)
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "pull", image,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr_bytes = await proc.communicate()
            if proc.returncode != 0:
                logger.error(
                    "docker pull %s failed: %s",
                    image,
                    stderr_bytes.decode(errors="replace"),
                )
                return False
            logger.info("Pulled image: %s", image)
            return True
        except Exception as exc:
            logger.error("pull_image error: %s", exc)
            return False

    async def list_available(self) -> list[str]:
        """Return a list of locally available Docker image names."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "images", "--format", "{{.Repository}}:{{.Tag}}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_bytes, _ = await proc.communicate()
            lines = stdout_bytes.decode(errors="replace").splitlines()
            return [ln.strip() for ln in lines if ln.strip() and ln.strip() != "<none>:<none>"]
        except Exception as exc:
            logger.error("list_available error: %s", exc)
            return []

    async def image_exists(self, image: str) -> bool:
        """Return True if the image is available locally."""
        available = await self.list_available()
        # Normalise: add :latest when no tag given
        normalized = image if ":" in image else f"{image}:latest"
        return normalized in available or image in available

    async def pull_prebuilt(self) -> None:
        """Pull all images in PREBUILT_IMAGES (intended for startup)."""
        for image in PREBUILT_IMAGES:
            await self.pull_image(image)
