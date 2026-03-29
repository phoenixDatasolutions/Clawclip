"""Retry strategies for the self-healing module."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class RetryStrategy(str, Enum):
    """Available recovery strategies when an agent task fails."""

    SAME_MODEL = "same_model"
    DIFFERENT_MODEL = "different_model"
    REPHRASE_PROMPT = "rephrase_prompt"
    DIFFERENT_AGENT = "different_agent"
    ESCALATE_HUMAN = "escalate_human"


@dataclass
class StrategyConfig:
    """A single retry strategy together with its configuration parameters."""

    strategy: RetryStrategy
    config: dict[str, Any] = field(default_factory=dict)


def get_default_strategies() -> list[StrategyConfig]:
    """Return the standard four-stage escalation ladder:

    1. Rephrase the prompt (add "Think step by step").
    2. Switch to a fallback model.
    3. Reassign to a different agent type.
    4. Escalate to a human operator.
    """
    return [
        StrategyConfig(
            strategy=RetryStrategy.REPHRASE_PROMPT,
            config={"prefix": "Think step by step.\n\n"},
        ),
        StrategyConfig(
            strategy=RetryStrategy.DIFFERENT_MODEL,
            config={"fallback_model": "gpt-4o-mini"},
        ),
        StrategyConfig(
            strategy=RetryStrategy.DIFFERENT_AGENT,
            config={"agent_type": "coordinator"},
        ),
        StrategyConfig(
            strategy=RetryStrategy.ESCALATE_HUMAN,
            config={},
        ),
    ]
