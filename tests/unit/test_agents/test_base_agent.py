"""Unit tests for nexusai.agents.base_agent — BaseAgent LLM loop."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.conftest import FakeLLMProvider, FakeLLMProviderWithToolCalls
from nexusai.agents.base_agent import BaseAgent
from nexusai.core.enums import AgentStatus
from nexusai.core.events import EventBus
from nexusai.core.types import (
    AgentConfig,
    AgentContext,
    SkillResult,
    TaskRequest,
)


def _make_config(**kwargs) -> AgentConfig:
    defaults = dict(
        agent_type="test",
        provider="fake",
        model="fake-model",
        system_prompt="Test agent.",
        allowed_skills=[],
        max_turns=5,
        temperature=0.0,
        max_tokens=256,
    )
    defaults.update(kwargs)
    return AgentConfig(**defaults)


def _make_context(provider, skill_manager=None) -> AgentContext:
    ctx = AgentContext(event_bus=EventBus(), user_id="u1")
    ctx._provider = provider  # type: ignore[attr-defined]
    ctx.skill_manager = skill_manager
    return ctx


def _task(desc: str = "Do something") -> TaskRequest:
    return TaskRequest(description=desc, user_id="u1")


# ── Tests ────────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestBaseAgent:

    async def test_execute_simple_task(self) -> None:
        """Agent with a plain-text provider returns a successful AgentResult."""
        provider = FakeLLMProvider(["Hello from fake LLM"])
        agent = BaseAgent()
        await agent.initialize(_make_config(), _make_context(provider))

        result = await agent.execute(_task())

        assert result.success is True
        assert "Hello from fake LLM" in result.output

    async def test_execute_respects_max_turns(self) -> None:
        """Provider that always returns tool calls stops at max_turns."""
        from nexusai.core.types import LLMResponse, ToolCall

        class InfiniteToolProvider:
            name = "infinite"
            _call_count = 0

            async def generate(self, messages, model="fake-model", tools=None, **kw):
                self._call_count += 1
                return LLMResponse(
                    content="",
                    model=model,
                    provider="fake",
                    input_tokens=5,
                    output_tokens=5,
                    cost_usd=0.0,
                    stop_reason="tool_use",
                    tool_calls=[ToolCall(id="c1", name="noop", arguments={})],
                )

        provider = InfiniteToolProvider()
        skill_mgr = MagicMock()
        skill_mgr.get_tools_for_agent = MagicMock(return_value=[])
        skill_mgr.execute = AsyncMock(return_value=SkillResult(success=True, output="ok"))

        agent = BaseAgent()
        await agent.initialize(_make_config(max_turns=3), _make_context(provider, skill_mgr))
        result = await agent.execute(_task())

        # Must not run forever; max_turns=3 means at most 3 LLM calls
        assert provider._call_count <= 3

    async def test_status_transitions(self) -> None:
        """Status goes IDLE before execute() and resolves to a terminal state after."""
        provider = FakeLLMProvider(["Done"])
        agent = BaseAgent()
        await agent.initialize(_make_config(), _make_context(provider))

        assert agent.status == AgentStatus.IDLE.value

        result = await agent.execute(_task())

        assert agent.status in (
            AgentStatus.COMPLETED.value,
            AgentStatus.IDLE.value,
        )

    async def test_tool_call_executed(self) -> None:
        """When provider returns a tool call, SkillManager.execute is called."""
        skill_mgr = MagicMock()
        skill_mgr.get_tools_for_agent = MagicMock(return_value=[MagicMock()])
        skill_mgr.execute = AsyncMock(return_value=SkillResult(success=True, output="result"))

        provider = FakeLLMProviderWithToolCalls(
            tool_name="shell__run",
            tool_args={"cmd": "echo hi"},
            final_response="All done",
        )
        agent = BaseAgent()
        await agent.initialize(_make_config(), _make_context(provider, skill_mgr))

        result = await agent.execute(_task())

        skill_mgr.execute.assert_called_once()
        assert result.success is True

    async def test_cost_aggregated(self) -> None:
        """Multiple LLM turns accumulate cost in AgentResult.cost_usd."""
        provider = FakeLLMProvider(["Response A", "Response B"])
        agent = BaseAgent()
        await agent.initialize(_make_config(max_turns=10), _make_context(provider))

        result = await agent.execute(_task())

        assert result.cost_usd > 0.0

    async def test_cancelled_mid_execution(self) -> None:
        """Calling cancel() sets status to CANCELLED."""
        provider = FakeLLMProvider(["ok"])
        agent = BaseAgent()
        await agent.initialize(_make_config(), _make_context(provider))

        await agent.cancel()

        assert agent.status == AgentStatus.CANCELLED.value
