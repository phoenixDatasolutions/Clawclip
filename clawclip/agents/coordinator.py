"""Coordinator Agent — analyzes tasks, decomposes them, and delegates to specialized agents."""

from __future__ import annotations

import json
import logging
from typing import Any

from clawclip.agents.base_agent import BaseAgent
from clawclip.core.types import (
    AgentConfig,
    AgentContext,
    AgentResult,
    LLMMessage,
    TaskRequest,
)

logger = logging.getLogger(__name__)

COORDINATOR_SYSTEM_PROMPT = """You are the Coordinator Agent for ClawClip, a multi-agent AI platform.

Your job is to:
1. Analyze incoming user tasks
2. Determine if the task needs a single agent or multiple agents
3. For simple tasks: handle them directly
4. For complex tasks: decompose into sub-tasks and specify which agent type should handle each

Available agent types:
- code: Code generation, review, refactoring, debugging. Has shell, files, and git tools.
- research: Web search, documentation lookup, information synthesis. Has web_search tools.
- system: Shell commands, process management, system monitoring, screenshots. Has shell, monitor, screenshot tools.
- devops: Git workflows, CI/CD, deployment automation. Has shell, git, ci_cd, deployment tools.

When you need to delegate, respond with a JSON block:
```json
{
    "plan": "Brief description of your approach",
    "subtasks": [
        {"agent": "code", "task": "description of what this agent should do"},
        {"agent": "research", "task": "description of what this agent should do"}
    ],
    "parallel": true
}
```

If you can handle the task directly (simple questions, no tools needed), just respond normally.
"""


class CoordinatorAgent(BaseAgent):
    """Coordinator agent that analyzes tasks and delegates to specialized agents.

    For simple tasks, handles directly. For complex tasks, decomposes into
    sub-tasks and delegates to the appropriate specialized agents.
    """

    def __init__(self) -> None:
        super().__init__()
        self._name = "coordinator"
        self._description = "Routes tasks to specialized agents"

    async def initialize(self, config: AgentConfig, context: AgentContext) -> None:
        """Initialize with coordinator-specific system prompt."""
        # Merge coordinator system prompt with any custom prompt
        if not config.system_prompt or config.system_prompt.strip() == "":
            config = AgentConfig(
                agent_type=config.agent_type,
                provider=config.provider,
                model=config.model,
                system_prompt=COORDINATOR_SYSTEM_PROMPT,
                allowed_skills=config.allowed_skills,
                max_turns=config.max_turns,
                temperature=config.temperature,
                max_tokens=config.max_tokens,
                max_delegations=config.max_delegations,
            )
        await super().initialize(config, context)

    async def execute(self, task: TaskRequest) -> AgentResult:
        """Execute a task, potentially delegating to sub-agents."""
        if not self._config or not self._context:
            raise RuntimeError("Agent not initialized.")

        # First, get the coordinator's analysis
        result = await super().execute(task)

        if not result.success:
            return result

        # Check if the response contains a delegation plan
        delegation_plan = self._parse_delegation(result.output)
        if delegation_plan and delegation_plan.get("subtasks"):
            return await self._execute_delegation(task, delegation_plan, result.cost_usd)

        # Direct response — no delegation needed
        return result

    def _parse_delegation(self, output: str) -> dict[str, Any] | None:
        """Try to extract a delegation plan from the coordinator's response."""
        try:
            # Look for JSON block in the response
            start = output.find("```json")
            if start == -1:
                start = output.find("{")
                if start == -1:
                    return None
                end = output.rfind("}") + 1
            else:
                start = output.find("{", start)
                end = output.find("```", start)
                if end == -1:
                    end = output.rfind("}") + 1
                else:
                    end = output.rfind("}", start, end) + 1

            if start == -1 or end <= start:
                return None

            json_str = output[start:end]
            plan = json.loads(json_str)

            if "subtasks" in plan and isinstance(plan["subtasks"], list):
                return plan
        except (json.JSONDecodeError, ValueError):
            pass
        return None

    async def _execute_delegation(
        self,
        original_task: TaskRequest,
        plan: dict[str, Any],
        coordinator_cost: float,
    ) -> AgentResult:
        """Execute a delegation plan by spawning sub-agents."""
        subtasks = plan.get("subtasks", [])
        is_parallel = plan.get("parallel", False)

        if not subtasks:
            return AgentResult(
                success=True,
                output="No subtasks to execute",
                cost_usd=coordinator_cost,
                agent_id=self._agent_id,
                agent_type="coordinator",
            )

        logger.info(
            "Coordinator delegating %d subtasks (%s)",
            len(subtasks),
            "parallel" if is_parallel else "sequential",
        )

        # Check delegation limit
        max_delegations = self._config.max_delegations if self._config else 5
        if len(subtasks) > max_delegations:
            subtasks = subtasks[:max_delegations]
            logger.warning("Truncated subtasks to max_delegations=%d", max_delegations)

        # Import engine here to avoid circular imports
        # In practice, the engine is accessed via the context
        sub_results: list[AgentResult] = []
        total_cost = coordinator_cost

        for subtask_def in subtasks:
            agent_type = subtask_def.get("agent", "code")
            task_desc = subtask_def.get("task", "")

            sub_task = TaskRequest(
                description=task_desc,
                user_id=original_task.user_id,
                conversation_id=original_task.conversation_id,
                platform=original_task.platform,
                channel_id=original_task.channel_id,
                parent_task_id=original_task.task_id,
            )

            # For now, execute sequentially
            # TODO: parallel execution via AgentEngine.execute_parallel()
            try:
                # Create a sub-agent directly
                from clawclip.agents.base_agent import BaseAgent as SubAgent

                sub_agent = SubAgent()
                sub_config = AgentConfig(
                    agent_type=agent_type,
                    provider=self._config.provider if self._config else "claude_api",
                    model=self._config.model if self._config else "claude-sonnet-4-20250514",
                    system_prompt=f"You are a {agent_type} agent. {task_desc}",
                    allowed_skills=self._config.allowed_skills if self._config else [],
                )

                sub_context = AgentContext(
                    event_bus=self._context.event_bus if self._context else None,
                    skill_manager=self._context.skill_manager if self._context else None,
                    storage=self._context.storage if self._context else None,
                    parent_agent_id=self._agent_id,
                    user_id=original_task.user_id,
                )
                if self._context and hasattr(self._context, "_provider"):
                    sub_context._provider = self._context._provider  # type: ignore[attr-defined]

                await sub_agent.initialize(sub_config, sub_context)
                result = await sub_agent.execute(sub_task)
                sub_results.append(result)
                total_cost += result.cost_usd

            except Exception as e:
                logger.exception("Sub-agent %s failed", agent_type)
                sub_results.append(AgentResult(
                    success=False, output=str(e),
                    agent_type=agent_type,
                ))

        # Synthesize final response
        synthesis = self._synthesize_results(plan, sub_results)

        return AgentResult(
            success=all(r.success for r in sub_results),
            output=synthesis,
            cost_usd=total_cost,
            agent_id=self._agent_id,
            agent_type="coordinator",
            sub_results=sub_results,
        )

    def _synthesize_results(
        self,
        plan: dict[str, Any],
        results: list[AgentResult],
    ) -> str:
        """Combine sub-agent results into a coherent response."""
        parts = [f"**Plan:** {plan.get('plan', 'Multi-agent execution')}\n"]

        for i, result in enumerate(results):
            status = "completed" if result.success else "failed"
            parts.append(f"\n**Agent {i+1} ({result.agent_type})** [{status}]:")
            parts.append(result.output[:2000])  # Truncate very long outputs

        return "\n".join(parts)
