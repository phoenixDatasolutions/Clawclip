"""System Agent — specialized for system monitoring, process management, and diagnostics."""

from __future__ import annotations

import logging

from nexusai.agents.base_agent import BaseAgent
from nexusai.core.types import AgentConfig, AgentContext

logger = logging.getLogger(__name__)

DEFAULT_SYSTEM_PROMPT = """You are a cautious and methodical systems administrator and diagnostics specialist.

Your responsibilities:
- Monitor system health: CPU, memory, disk, network, and running processes
- Diagnose performance bottlenecks, resource exhaustion, and service failures
- Manage OS-level processes: inspect, start, stop, and restart services safely
- Capture screenshots or system state snapshots to document current conditions

Standards you uphold:
- SAFETY FIRST — always describe what a command will do before running it on a live system
- Prefer read-only diagnostic commands (ps, top, df, netstat) before any destructive action
- Never kill or stop a process without confirming it is safe to do so
- When unsure about the impact of an operation, ask for confirmation rather than proceeding
- Document every significant action taken and its observed outcome
- If a command fails, capture the full error output and explain the likely cause

When using tools:
- Use the shell skill for command-line diagnostics; prefer non-destructive flags first
- Use the monitor skill for structured metrics collection (CPU, memory, disk, network)
- Use the screenshot skill to capture the current state of the GUI or terminal for reporting
- Escalate to the user before any action that could cause downtime or data loss
"""


class SystemAgent(BaseAgent):
    """Specialised agent for system monitoring, process management, and diagnostics.

    Extends :class:`~nexusai.agents.base_agent.BaseAgent` with a systems-focused
    system prompt and a curated set of allowed skills.
    """

    def __init__(self) -> None:
        super().__init__()
        self._name = "system"
        self._description = "Handles system monitoring, process management, and diagnostics"
        self._default_allowed_skills = ["shell", "monitor", "screenshot"]

    async def initialize(self, config: AgentConfig, context: AgentContext) -> None:
        """Initialize with system-specialist defaults, preserving any overrides in *config*."""
        if not config.system_prompt or not config.system_prompt.strip():
            config = AgentConfig(
                agent_type=config.agent_type,
                provider=config.provider,
                model=config.model,
                system_prompt=DEFAULT_SYSTEM_PROMPT,
                allowed_skills=config.allowed_skills or self._default_allowed_skills,
                max_turns=config.max_turns,
                temperature=config.temperature,
                max_tokens=config.max_tokens,
                max_delegations=config.max_delegations,
                extra=config.extra,
            )
        elif not config.allowed_skills:
            config = AgentConfig(
                agent_type=config.agent_type,
                provider=config.provider,
                model=config.model,
                system_prompt=config.system_prompt,
                allowed_skills=self._default_allowed_skills,
                max_turns=config.max_turns,
                temperature=config.temperature,
                max_tokens=config.max_tokens,
                max_delegations=config.max_delegations,
                extra=config.extra,
            )

        await super().initialize(config, context)

        self._name = "system"
        self._description = "Handles system monitoring, process management, and diagnostics"
        logger.info("SystemAgent initialized (agent_id=%s)", self._agent_id[:8])
