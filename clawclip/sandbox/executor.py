"""Command execution inside a running Docker sandbox container."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)


class SandboxExecutor:
    """Executes commands and file operations inside a Docker container.

    Uses ``docker exec`` via subprocess so no Docker SDK dependency is needed.
    """

    def __init__(self, container_id: str, work_dir: str = "/workspace") -> None:
        self._container_id = container_id
        self._work_dir = work_dir

    # ── Command execution ────────────────────────────────────────

    async def exec(
        self,
        command: str,
        timeout: float = 60.0,
    ) -> tuple[int, str, str]:
        """Run a shell command inside the container.

        Returns:
            (returncode, stdout, stderr)
        """
        docker_cmd = [
            "docker", "exec",
            "--workdir", self._work_dir,
            self._container_id,
            "sh", "-c", command,
        ]
        try:
            proc = await asyncio.wait_for(
                asyncio.create_subprocess_exec(
                    *docker_cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                ),
                timeout=5.0,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
            returncode = proc.returncode if proc.returncode is not None else -1
            return returncode, stdout_bytes.decode(errors="replace"), stderr_bytes.decode(errors="replace")
        except asyncio.TimeoutError:
            logger.warning("Command timed out in container %s", self._container_id[:12])
            try:
                proc.kill()  # type: ignore[possibly-undefined]
            except Exception:
                pass
            return -1, "", "Execution timed out"
        except Exception as exc:
            logger.error("exec failed in container %s: %s", self._container_id[:12], exc)
            return -1, "", str(exc)

    # ── File operations ──────────────────────────────────────────

    async def copy_file(self, local_path: str, container_path: str) -> None:
        """Copy a local file into the container."""
        cmd = ["docker", "cp", local_path, f"{self._container_id}:{container_path}"]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr_bytes = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(
                f"docker cp failed: {stderr_bytes.decode(errors='replace')}"
            )

    async def read_file(self, container_path: str) -> bytes:
        """Read a file from inside the container and return its bytes."""
        cmd = ["docker", "exec", self._container_id, "cat", container_path]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(
                f"read_file failed: {stderr_bytes.decode(errors='replace')}"
            )
        return stdout_bytes
