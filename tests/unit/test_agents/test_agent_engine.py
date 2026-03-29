"""Unit tests for nexusai.agents.engine — AgentEngine lifecycle and parallel execution."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from tests.conftest import FakeLLMProvider
from nexusai.agents.engine import AgentEngine
from nexusai.core.events import AgentTaskCompleted, AgentTaskStarted, EventBus
from nexusai.core.registry import Registry
from nexusai.core.types import AgentConfig, TaskRequest


def _make_engine(
    responses: list[str] | None = None,
    agent_type: str = "coordinator",
) -> AgentEngine:
    provider = FakeLLMProvider(responses or ["Engine fake response"])
    reg = Registry("providers")
    reg.register("fake", provider)

    config = AgentConfig(
        agent_type=agent_type,
        provider="fake",
        model="fake-model",
        system_prompt="Test.",
        allowed_skills=[],
        max_turns=3,
        temperature=0.0,
    )
    bus = EventBus()
    return AgentEngine(
        event_bus=bus,
        provider_registry=reg,
        agent_configs={agent_type: config},
    ), bus


def _task(desc: str = "Test task") -> TaskRequest:
    return TaskRequest(description=desc, user_id="u1")


# ── Tests ────────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestAgentEngine:

    async def test_execute_task_returns_result(self) -> None:
        """engine.execute_task() returns an AgentResult with success=True."""
        engine, _ = _make_engine(["Hello world"], agent_type="coordinator")
        result = await engine.execute_task(_task(), agent_type="coordinator")

        assert result.success is True
        assert "Hello world" in result.output

    async def test_execute_task_uses_coordinator(self) -> None:
        """No agent_type specified → defaults to coordinator."""
        engine, _ = _make_engine(["Coordinator here"], agent_type="coordinator")
        result = await engine.execute_task(_task())

        assert result.success is True

    async def test_execute_parallel(self) -> None:
        """execute_parallel([task1, task2]) returns both results."""
        engine, _ = _make_engine(["Result A"], agent_type="coordinator")
        tasks = [
            ("coordinator", _task("Task A")),
            ("coordinator", _task("Task B")),
        ]
        results = await engine.execute_parallel(tasks)

        assert len(results) == 2
        assert all(r.success for r in results)

    async def test_get_running_agents(self) -> None:
        """Agents are tracked in get_running_agents() while executing."""
        engine, _ = _make_engine(["done"], agent_type="coordinator")

        # Spawn an agent directly and verify tracking
        from nexusai.core.types import AgentContext

        ctx = AgentContext(event_bus=engine._event_bus, user_id="u1")
        from tests.conftest import FakeLLMProvider as FLP
        ctx._provider = FLP(["hi"])  # type: ignore[attr-defined]

        config = engine._agent_configs["coordinator"]
        agent = await engine.spawn_agent("coordinator", config, ctx)

        assert len(engine.get_running_agents()) == 1
        assert engine.get_agent(agent.agent_id) is agent

    async def test_cancel_agent(self) -> None:
        """cancel_agent(id) marks the agent as cancelled and returns True."""
        engine, _ = _make_engine(["done"], agent_type="coordinator")
        from nexusai.core.types import AgentContext

        ctx = AgentContext(event_bus=engine._event_bus, user_id="u1")
        from tests.conftest import FakeLLMProvider as FLP
        ctx._provider = FLP(["hi"])  # type: ignore[attr-defined]

        config = engine._agent_configs["coordinator"]
        agent = await engine.spawn_agent("coordinator", config, ctx)

        cancelled = await engine.cancel_agent(agent.agent_id)
        assert cancelled is True
        assert agent.status == "cancelled"

    async def test_events_published(self) -> None:
        """execute_task publishes AgentTaskStarted and AgentTaskCompleted events."""
        engine, bus = _make_engine(["Response"], agent_type="coordinator")

        started: list = []
        completed: list = []
        bus.subscribe(AgentTaskStarted, lambda e: started.append(e))
        bus.subscribe(AgentTaskCompleted, lambda e: completed.append(e))

        await engine.execute_task(_task(), agent_type="coordinator")

        assert len(started) >= 1
        assert len(completed) >= 1
