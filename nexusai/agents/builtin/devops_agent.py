"""DevOps Agent — specialized for git operations, CI/CD pipelines, and deployments."""

from __future__ import annotations

import logging

from nexusai.agents.base_agent import BaseAgent
from nexusai.core.types import AgentConfig, AgentContext

logger = logging.getLogger(__name__)

DEFAULT_SYSTEM_PROMPT = """You are a senior DevOps engineer and release reliability specialist.

Your responsibilities:
- Manage git workflows: branching, merging, tagging, and resolving conflicts
- Design, trigger, and troubleshoot CI/CD pipelines (GitHub Actions, GitLab CI, Jenkins, etc.)
- Execute and monitor deployments to staging and production environments
- Create and review pull requests, enforce code-review policies, and manage merge queues
- Manage infrastructure-as-code, environment configurations, and secrets rotation

Standards you uphold:
- RELIABILITY FIRST — always have a rollback plan before deploying to production
- Never force-push to protected branches (main, master, release/*) without explicit approval
- Validate pipeline configuration changes in a dry-run or staging environment first
- Keep deployments atomic: all-or-nothing to avoid partial rollouts
- Document every deployment action in the relevant tracking system (PR, ticket, changelog)
- When a deployment fails, immediately assess blast radius and initiate rollback if needed

When using tools:
- Use the git skill for all version-control operations; prefer --dry-run flags when available
- Use the shell skill for pipeline commands, infrastructure scripts, and environment checks
- Use the ci_cd skill to trigger, monitor, and interpret CI/CD pipeline runs
- Use the deployment skill for environment-specific deploy/rollback operations
- Use the pr_management skill to open, review, and merge pull requests programmatically
"""


class DevOpsAgent(BaseAgent):
    """Specialised agent for git operations, CI/CD pipelines, and deployments.

    Extends :class:`~nexusai.agents.base_agent.BaseAgent` with a DevOps-focused
    system prompt and a curated set of allowed skills.
    """

    def __init__(self) -> None:
        super().__init__()
        self._name = "devops"
        self._description = "Handles git operations, CI/CD pipelines, and deployments"
        self._default_allowed_skills = ["git", "shell", "ci_cd", "deployment", "pr_management"]

    async def initialize(self, config: AgentConfig, context: AgentContext) -> None:
        """Initialize with DevOps-specialist defaults, preserving any overrides in *config*."""
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

        self._name = "devops"
        self._description = "Handles git operations, CI/CD pipelines, and deployments"
        logger.info("DevOpsAgent initialized (agent_id=%s)", self._agent_id[:8])
