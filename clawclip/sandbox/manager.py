"""SandboxManager — create, destroy, and use Docker sandbox containers."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import tempfile
import os
from collections.abc import AsyncGenerator
from typing import Any

from clawclip.sandbox.config import DEFAULT_IMAGES, SandboxConfig
from clawclip.sandbox.executor import SandboxExecutor

logger = logging.getLogger(__name__)


class SandboxManager:
    """Creates and destroys Docker containers for isolated code execution.

    Falls back to a local subprocess with timeout when Docker is unavailable.
    """

    def __init__(self, config: SandboxConfig | None = None) -> None:
        self._default_config = config or SandboxConfig()

    # ── Docker availability ──────────────────────────────────────

    @staticmethod
    async def is_docker_available() -> bool:
        """Return True if the Docker CLI is accessible."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "info",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()
            return proc.returncode == 0
        except Exception:
            return False

    # ── Container lifecycle ──────────────────────────────────────

    async def create(self, config: SandboxConfig | None = None) -> str:
        """Start a container and return its container_id."""
        cfg = config or self._default_config
        cmd = [
            "docker", "run",
            "--detach",
            "--rm",
            f"--memory={cfg.memory_limit}",
            f"--cpus={cfg.cpu_limit}",
            "--workdir", cfg.work_dir,
        ]
        if not cfg.network_access:
            cmd += ["--network", "none"]
        for key, val in cfg.env_vars.items():
            cmd += ["-e", f"{key}={val}"]
        cmd += [cfg.image, "sleep", str(cfg.timeout_seconds + 30)]

        logger.debug("Creating sandbox container: %s", " ".join(cmd))
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_bytes, stderr_bytes = await proc.communicate()
            if proc.returncode != 0:
                raise RuntimeError(
                    f"docker run failed: {stderr_bytes.decode(errors='replace')}"
                )
            container_id = stdout_bytes.decode().strip()
            logger.info("Sandbox created: %s", container_id[:12])
            return container_id
        except Exception as exc:
            logger.error("Failed to create sandbox: %s", exc)
            raise

    async def destroy(self, container_id: str) -> None:
        """Stop and remove a container (best-effort)."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "rm", "-f", container_id,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()
            logger.debug("Sandbox destroyed: %s", container_id[:12])
        except Exception as exc:
            logger.warning("destroy failed for %s: %s", container_id[:12], exc)

    # ── Executor access ──────────────────────────────────────────

    async def get_executor(self, container_id: str) -> SandboxExecutor:
        """Return an executor bound to an existing container."""
        cfg = self._default_config
        return SandboxExecutor(container_id, work_dir=cfg.work_dir)

    # ── High-level run ───────────────────────────────────────────

    async def run_in_sandbox(
        self,
        code: str,
        language: str = "python",
        config: SandboxConfig | None = None,
    ) -> tuple[int, str, str]:
        """Run code in a fresh container, then destroy it.

        Falls back to local execution with a timeout if Docker is unavailable.
        Returns (returncode, stdout, stderr).
        """
        cfg = config or SandboxConfig(image=DEFAULT_IMAGES.get(language, "python:3.12-slim"))

        if not await self.is_docker_available():
            logger.warning("Docker unavailable — running locally with timeout")
            return await self._run_locally(code, language, cfg.timeout_seconds)

        container_id = await self.create(cfg)
        try:
            executor = SandboxExecutor(container_id, work_dir=cfg.work_dir)
            run_cmd = self._build_run_command(code, language)
            return await executor.exec(run_cmd, timeout=float(cfg.timeout_seconds))
        finally:
            await self.destroy(container_id)

    # ── Context manager ──────────────────────────────────────────

    @contextlib.asynccontextmanager
    async def sandbox(
        self, config: SandboxConfig | None = None
    ) -> AsyncGenerator[SandboxExecutor, None]:
        """Async context manager that yields a live SandboxExecutor.

        Example::

            async with manager.sandbox(cfg) as executor:
                rc, out, err = await executor.exec("python -c 'print(1)'")
        """
        container_id = await self.create(config)
        try:
            yield await self.get_executor(container_id)
        finally:
            await self.destroy(container_id)

    # ── Helpers ──────────────────────────────────────────────────

    @staticmethod
    def _build_run_command(code: str, language: str) -> str:
        """Return a shell command string to execute *code* in the container."""
        escaped = code.replace("'", "'\"'\"'")
        commands: dict[str, str] = {
            "python": f"python3 -c '{escaped}'",
            "node": f"node -e '{escaped}'",
            "bash": f"sh -c '{escaped}'",
            "go": "go run /tmp/main.go",  # caller must copy file first
            "rust": "rustc /tmp/main.rs -o /tmp/out && /tmp/out",
        }
        return commands.get(language, f"sh -c '{escaped}'")

    @staticmethod
    async def _run_locally(
        code: str,
        language: str,
        timeout: int,
    ) -> tuple[int, str, str]:
        """Fallback: run code in a local subprocess with a timeout."""
        lang_cmd: dict[str, list[str]] = {
            "python": ["python3", "-c", code],
            "node": ["node", "-e", code],
            "bash": ["sh", "-c", code],
        }
        cmd = lang_cmd.get(language, ["sh", "-c", code])
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=float(timeout)
            )
            rc = proc.returncode if proc.returncode is not None else -1
            return rc, stdout_bytes.decode(errors="replace"), stderr_bytes.decode(errors="replace")
        except asyncio.TimeoutError:
            try:
                proc.kill()  # type: ignore[possibly-undefined]
            except Exception:
                pass
            return -1, "", "Local execution timed out"
        except Exception as exc:
            return -1, "", str(exc)
