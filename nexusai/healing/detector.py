"""Failure detector — classify AgentResult failures into FailureTypes."""

from __future__ import annotations

import logging
import re
from enum import Enum
from typing import Any

from nexusai.core.types import AgentResult

logger = logging.getLogger(__name__)


class FailureType(str, Enum):
    """Enumeration of recognisable failure categories."""

    TIMEOUT = "timeout"
    MODEL_ERROR = "model_error"
    TOOL_FAILED = "tool_failed"
    INVALID_OUTPUT = "invalid_output"
    COST_LIMIT = "cost_limit"


# Failures that make sense to retry automatically
RETRYABLE_FAILURES: set[FailureType] = {
    FailureType.TIMEOUT,
    FailureType.MODEL_ERROR,
    FailureType.TOOL_FAILED,
    FailureType.INVALID_OUTPUT,
}

# Pattern table: (compiled regex, FailureType)
_PATTERNS: list[tuple[re.Pattern[str], FailureType]] = [
    (re.compile(r"timeout|timed? out|deadline exceeded", re.I), FailureType.TIMEOUT),
    (re.compile(r"rate.?limit|quota|429", re.I), FailureType.MODEL_ERROR),
    (re.compile(r"model error|api error|provider error|500|503", re.I), FailureType.MODEL_ERROR),
    (re.compile(r"tool.*(fail|error)|skill.*(fail|error)", re.I), FailureType.TOOL_FAILED),
    (re.compile(r"cost.?limit|budget.?exceeded|max.?cost", re.I), FailureType.COST_LIMIT),
    (re.compile(r"invalid.?output|parse.?error|json.?error|format.?error", re.I), FailureType.INVALID_OUTPUT),
]


def detect_failure(result: AgentResult) -> FailureType | None:
    """Inspect an AgentResult and return the most likely FailureType.

    Returns None when the result is successful or the failure is unclassified.
    """
    if result.success:
        return None

    # Gather all text signals
    error_text = " ".join(filter(None, [
        result.output,
        getattr(result, "error", None),
    ]))

    for pattern, failure_type in _PATTERNS:
        if pattern.search(error_text):
            logger.debug("Detected failure type %s from: %s", failure_type, error_text[:80])
            return failure_type

    # Default fallback — unclassified failure still needs attention
    logger.debug("Unclassified failure: %s", error_text[:80])
    return FailureType.INVALID_OUTPUT


def should_retry(
    failure_type: FailureType,
    attempt: int,
    config: dict[str, Any] | None = None,
) -> bool:
    """Return True when the failure is worth retrying on *attempt* N.

    Args:
        failure_type: Classification from :func:`detect_failure`.
        attempt: Zero-based retry count (0 = first attempt already made).
        config: Optional override dict with key ``max_retries`` (default 3).
    """
    max_retries = (config or {}).get("max_retries", 3)
    if failure_type not in RETRYABLE_FAILURES:
        return False
    return attempt < max_retries
