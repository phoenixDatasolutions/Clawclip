"""Code Agent — specialized for code generation, review, debugging, and refactoring."""

from __future__ import annotations

import logging

from nexusai.agents.base_agent import BaseAgent
from nexusai.core.types import AgentConfig, AgentContext

logger = logging.getLogger(__name__)

DEFAULT_SYSTEM_PROMPT = """You are a expert software engineer and code specialist.

Your responsibilities:
- Write clean, well-documented, production-ready code in any language
- Review code for correctness, readability, performance, and security vulnerabilities
- Debug failing tests, runtime errors, and logic bugs with systematic analysis
- Refactor existing code to improve structure, reduce duplication, and follow best practices

Standards you uphold:
- Always include appropriate tests alongside new code (unit, integration where relevant)
- Flag security issues explicitly (e.g. injection, auth bypass, hardcoded secrets)
- Prefer idiomatic patterns for the language and ecosystem in use
- When modifying existing code, preserve the existing style unless asked to refactor
- Explain your reasoning concisely — don't just produce code, justify key decisions

When using tools:
- Use the shell skill to run tests, linters, or build commands and verify your work
- Use the files skill to read existing source before making changes
- Use the git skill to inspect history and create well-formed commits
- Use the code_review skill for structured diff analysis when available
"""


class CodeAgent(BaseAgent):
    """Specialised agent for code generation, debugging, review, and refactoring.

    Extends :class:`~nexusai.agents.base_agent.BaseAgent` with a code-focused
    system prompt and a curated set of allowed skills.
    """

    def __init__(self) -> None:
        super().__init__()
        self._name = "code"
        self._description = "Handles code generation, review, debugging, and refactoring"
        self._default_allowed_skills = ["shell", "files", "git", "code_review"]

    async def initialize(self, config: AgentConfig, context: AgentContext) -> None:
        """Initialize with code-specialist defaults, preserving any overrides in *config*."""
        # Inject default system prompt if none was provided
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

        # Override name/description with our specialised values
        self._name = "code"
        self._description = "Handles code generation, review, debugging, and refactoring"
        logger.info("CodeAgent initialized (agent_id=%s)", self._agent_id[:8])
