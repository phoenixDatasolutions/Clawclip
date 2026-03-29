"""Test utilities and helper functions."""
from __future__ import annotations
import asyncio
from typing import Any
from nexusai.core.events import EventBus, Event


async def collect_events(event_bus: EventBus, event_type: type, count: int, timeout: float = 2.0) -> list:
    """Wait for `count` events of the given type, with timeout."""
    collected = []
    ready = asyncio.Event()

    async def handler(event):
        collected.append(event)
        if len(collected) >= count:
            ready.set()

    event_bus.subscribe(event_type, handler)
    try:
        await asyncio.wait_for(ready.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        pass
    finally:
        event_bus.unsubscribe(event_type, handler)
    return collected


def assert_skill_result_ok(result, expected_substring: str | None = None):
    """Assert a SkillResult is successful."""
    assert result.success, f"Skill failed: {result.output}"
    if expected_substring:
        assert expected_substring in result.output, f"Expected '{expected_substring}' in: {result.output}"


def assert_skill_result_fail(result, expected_substring: str | None = None):
    """Assert a SkillResult is a failure."""
    assert not result.success, f"Expected failure but got: {result.output}"
    if expected_substring:
        assert expected_substring in (result.output or result.error or ""), \
            f"Expected '{expected_substring}' in: {result.output}"
