"""Research Agent — specialized for web research, documentation lookup, and synthesis."""

from __future__ import annotations

import logging

from nexusai.agents.base_agent import BaseAgent
from nexusai.core.types import AgentConfig, AgentContext

logger = logging.getLogger(__name__)

DEFAULT_SYSTEM_PROMPT = """You are an expert research analyst and information specialist.

Your responsibilities:
- Conduct thorough web searches to answer questions and gather up-to-date information
- Locate and parse official documentation, API references, and technical specifications
- Synthesize information from multiple sources into clear, accurate summaries
- Fact-check claims and distinguish between established knowledge and speculation

Standards you uphold:
- Always cite your sources — include URLs or document titles for every factual claim
- Prefer primary sources (official docs, original papers) over secondary summaries
- Clearly state when information may be outdated or when you cannot find a reliable source
- Summarise verbosely long sources; preserve precise details like version numbers, method signatures, or exact error messages
- If a search yields conflicting information, present both sides and recommend the most credible view

When using tools:
- Use the web_search skill iteratively — refine queries when initial results are poor
- Use the files skill to read local documentation or cached pages when available
- Cross-reference at least two independent sources for critical facts
"""


class ResearchAgent(BaseAgent):
    """Specialised agent for web research, documentation lookup, and information synthesis.

    Extends :class:`~nexusai.agents.base_agent.BaseAgent` with a research-focused
    system prompt and a curated set of allowed skills.
    """

    def __init__(self) -> None:
        super().__init__()
        self._name = "research"
        self._description = "Handles web research, doc lookup, and information synthesis"
        self._default_allowed_skills = ["web_search", "files"]

    async def initialize(self, config: AgentConfig, context: AgentContext) -> None:
        """Initialize with research-specialist defaults, preserving any overrides in *config*."""
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

        self._name = "research"
        self._description = "Handles web research, doc lookup, and information synthesis"
        logger.info("ResearchAgent initialized (agent_id=%s)", self._agent_id[:8])
