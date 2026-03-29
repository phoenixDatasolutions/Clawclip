"""Escalation chains — retry loop with self-healing strategy selection."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from nexusai.core.types import AgentResult, TaskRequest
from nexusai.healing.detector import FailureType, detect_failure, should_retry
from nexusai.healing.strategies import (
    RetryStrategy,
    StrategyConfig,
    get_default_strategies,
)

logger = logging.getLogger(__name__)


@dataclass
class EscalationChain:
    """Defines how many retries are allowed and which strategies to apply."""

    max_retries: int = 3
    strategies: list[StrategyConfig] = field(default_factory=get_default_strategies)
    escalate_to_human: bool = True
    human_channel: str | None = None


class EscalationManager:
    """Executes a task with automatic self-healing retries.

    On each failure the next :class:`StrategyConfig` in the chain is applied
    before retrying.  After *max_retries* attempts, if *escalate_to_human* is
    set a human escalation notification is emitted via the event bus.
    """

    def __init__(self, event_bus: Any | None = None) -> None:
        self._event_bus = event_bus

    async def execute_with_healing(
        self,
        task: TaskRequest,
        agent_engine: Any,
        chain: EscalationChain | None = None,
    ) -> AgentResult:
        """Run *task* through *agent_engine*, retrying with escalating strategies.

        Args:
            task: The task to execute.
            agent_engine: An :class:`~nexusai.agents.engine.AgentEngine` instance.
            chain: Escalation chain configuration.  Uses defaults if omitted.

        Returns:
            The :class:`AgentResult` from the last attempt (successful or not).
        """
        if chain is None:
            chain = EscalationChain()

        current_task = task
        last_result: AgentResult = AgentResult(
            success=False, output="No attempts made"
        )

        for attempt in range(chain.max_retries + 1):
            logger.info(
                "Healing attempt %d/%d for task %s",
                attempt + 1,
                chain.max_retries + 1,
                task.task_id,
            )

            try:
                result = await agent_engine.execute_task(current_task)
            except Exception as exc:
                logger.error("Agent engine raised: %s", exc)
                result = AgentResult(
                    success=False,
                    output=f"Exception: {exc}",
                    agent_type=getattr(agent_engine, "_default_agent_type", "unknown"),
                )

            last_result = result

            if result.success:
                logger.info("Task %s succeeded on attempt %d", task.task_id, attempt + 1)
                return result

            failure_type = detect_failure(result)
            if failure_type is None:
                # should not happen — treat as success check passed above
                return result

            if not should_retry(failure_type, attempt, {"max_retries": chain.max_retries}):
                logger.warning(
                    "Failure type %s is not retryable, stopping.", failure_type
                )
                break

            # Pick the strategy for this attempt
            strategy_idx = min(attempt, len(chain.strategies) - 1)
            strategy_cfg = chain.strategies[strategy_idx]
            logger.info(
                "Applying strategy %s (attempt %d)",
                strategy_cfg.strategy,
                attempt + 1,
            )
            current_task = self._apply_strategy(current_task, strategy_cfg, result)

        # All retries exhausted
        if chain.escalate_to_human:
            await self._escalate_human(task, last_result, chain)

        return last_result

    # ── Strategy application ──────────────────────────────────────

    @staticmethod
    def _apply_strategy(
        task: TaskRequest,
        strategy_cfg: StrategyConfig,
        last_result: AgentResult,
    ) -> TaskRequest:
        """Return a (possibly modified) TaskRequest for the next attempt."""
        from dataclasses import replace

        strategy = strategy_cfg.strategy
        cfg = strategy_cfg.config

        if strategy == RetryStrategy.REPHRASE_PROMPT:
            prefix = cfg.get("prefix", "Think step by step.\n\n")
            return replace(task, description=prefix + task.description)

        if strategy == RetryStrategy.DIFFERENT_MODEL:
            # Store the fallback model in context so the engine can pick it up
            new_context = dict(task.context)
            new_context["override_model"] = cfg.get("fallback_model", "gpt-4o-mini")
            return replace(task, context=new_context)

        if strategy == RetryStrategy.DIFFERENT_AGENT:
            new_context = dict(task.context)
            new_context["override_agent_type"] = cfg.get("agent_type", "coordinator")
            return replace(task, context=new_context)

        # SAME_MODEL / ESCALATE_HUMAN — no task modification
        return task

    # ── Human escalation ──────────────────────────────────────────

    async def _escalate_human(
        self,
        task: TaskRequest,
        result: AgentResult,
        chain: EscalationChain,
    ) -> None:
        """Publish an ApprovalRequired or Notification event to alert a human."""
        logger.warning(
            "HUMAN ESCALATION required for task %s: %s",
            task.task_id,
            result.output[:200],
        )

        if self._event_bus is not None:
            try:
                from nexusai.core.events import ApprovalRequired

                await self._event_bus.publish(
                    ApprovalRequired(
                        source="healing.escalation",
                        operation="human_review",
                        details=(
                            f"Task {task.task_id!r} failed after all retries.\n"
                            f"Last error: {result.output[:500]}"
                        ),
                        user_id=task.user_id,
                        platform=task.platform or "",
                        channel_id=chain.human_channel or task.channel_id or "",
                    )
                )
            except Exception as exc:
                logger.error("Failed to publish escalation event: %s", exc)
