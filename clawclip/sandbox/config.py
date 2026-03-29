"""Sandbox configuration dataclasses and default image mappings."""

from __future__ import annotations

from dataclasses import dataclass, field


DEFAULT_IMAGES: dict[str, str] = {
    "python": "python:3.12-slim",
    "node": "node:20-slim",
    "go": "golang:1.23-alpine",
    "rust": "rust:1.82-slim",
    "bash": "alpine:3.20",
}


@dataclass
class SandboxConfig:
    """Configuration for a Docker sandbox container."""

    image: str = "python:3.12-slim"
    memory_limit: str = "512m"
    cpu_limit: float = 1.0
    network_access: bool = False
    timeout_seconds: int = 60
    work_dir: str = "/workspace"
    env_vars: dict[str, str] = field(default_factory=dict)
