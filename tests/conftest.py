"""Shared pytest fixtures for NexusAI test suite."""
from __future__ import annotations

import asyncio
import os
import tempfile
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from nexusai.core.events import EventBus
from nexusai.core.registry import Registry
from nexusai.core.types import (
    AgentConfig,
    AgentContext,
    AgentResult,
    LLMMessage,
    LLMResponse,
    LLMStreamEvent,
    SkillContext,
    SkillResult,
    TaskRequest,
    ToolCall,
    ToolDefinition,
    UsageStats,
)
from nexusai.core.enums import AgentStatus, MessageRole


# ── Fake LLM Provider ────────────────────────────────────────────

class FakeLLMProvider:
    """Deterministic LLM provider for testing. Returns predefined responses."""

    def __init__(self, responses: list[str] | None = None) -> None:
        self._responses = responses or ["I am a fake LLM response."]
        self._call_count = 0
        self.last_messages: list[LLMMessage] = []
        self.last_tools: list[ToolDefinition] = []
        self.name = "fake"

    async def generate(
        self,
        messages: list[LLMMessage],
        model: str = "fake-model",
        tools: list[ToolDefinition] | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        self.last_messages = messages
        self.last_tools = tools or []
        response_text = self._responses[self._call_count % len(self._responses)]
        self._call_count += 1
        return LLMResponse(
            content=response_text,
            model=model,
            provider="fake",
            input_tokens=10,
            output_tokens=20,
            cost_usd=0.0001,
            stop_reason="end_turn",
        )

    async def generate_stream(self, messages, model="fake-model", **kwargs):
        response = await self.generate(messages, model, **kwargs)
        yield LLMStreamEvent(event_type="text_delta", text=response.content)
        yield LLMStreamEvent(event_type="message_stop", text="")

    async def count_tokens(self, messages, model="fake-model") -> int:
        return sum(len(m.content or "") // 4 for m in messages)

    def estimate_cost(self, model, input_tokens, output_tokens) -> float:
        return 0.0

    def get_model_capabilities(self, model_id: str) -> int:
        return 0

    async def health_check(self) -> bool:
        return True

    async def list_models(self):
        return []


class FakeLLMProviderWithToolCalls(FakeLLMProvider):
    """Fake provider that returns a tool call on the first response, then text."""

    def __init__(self, tool_name: str, tool_args: dict, final_response: str) -> None:
        super().__init__()
        self.tool_name = tool_name
        self.tool_args = tool_args
        self.final_response = final_response

    async def generate(self, messages, model="fake-model", tools=None, **kwargs):
        self.last_messages = messages
        self._call_count += 1
        if self._call_count == 1 and tools:
            return LLMResponse(
                content="",
                model=model,
                provider="fake",
                input_tokens=10,
                output_tokens=5,
                cost_usd=0.0,
                stop_reason="tool_use",
                tool_calls=[ToolCall(
                    id="call_1",
                    name=self.tool_name,
                    arguments=self.tool_args,
                )],
            )
        return LLMResponse(
            content=self.final_response,
            model=model,
            provider="fake",
            input_tokens=15,
            output_tokens=30,
            cost_usd=0.0001,
            stop_reason="end_turn",
        )


# ── Core Fixtures ────────────────────────────────────────────────

@pytest.fixture
def event_bus() -> EventBus:
    return EventBus()


@pytest.fixture
def fake_provider() -> FakeLLMProvider:
    return FakeLLMProvider()


@pytest.fixture
def provider_registry(fake_provider) -> Registry:
    reg = Registry("providers")
    reg.register("fake", fake_provider)
    return reg


@pytest.fixture
def skill_context(tmp_path) -> SkillContext:
    return SkillContext(
        user_id="test-user",
        platform="test",
        working_directory=str(tmp_path),
        config={},
    )


@pytest.fixture
def agent_config() -> AgentConfig:
    return AgentConfig(
        agent_type="coordinator",
        provider="fake",
        model="fake-model",
        system_prompt="You are a test agent.",
        allowed_skills=["shell", "files", "git"],
        max_turns=5,
        temperature=0.0,
    )


@pytest.fixture
def agent_context(event_bus, tmp_path) -> AgentContext:
    return AgentContext(
        event_bus=event_bus,
        user_id="test-user",
        platform="test",
    )


@pytest.fixture
def task_request() -> TaskRequest:
    return TaskRequest(
        task_id="test-task-1",
        description="Test task description",
        user_id="test-user",
        platform="test",
        channel_id="test-channel",
    )


# ── Skill Manager Fixture ────────────────────────────────────────

@pytest.fixture
def skill_manager(event_bus):
    from nexusai.skills.manager import SkillManager
    from nexusai.skills.builtin.shell import ShellSkill
    from nexusai.skills.builtin.files import FileSkill
    from nexusai.skills.builtin.git import GitSkill

    skill_registry = Registry("skills")
    skill_registry.register("shell", ShellSkill())
    skill_registry.register("files", FileSkill())
    skill_registry.register("git", GitSkill())

    manager = SkillManager(skill_registry=skill_registry, event_bus=event_bus)
    manager.build_index()
    return manager


# ── Agent Engine Fixture ─────────────────────────────────────────

@pytest.fixture
def agent_engine(event_bus, provider_registry, skill_manager):
    from nexusai.agents.engine import AgentEngine
    return AgentEngine(
        event_bus=event_bus,
        provider_registry=provider_registry,
        skill_manager=skill_manager,
    )


# ── Database Fixtures ────────────────────────────────────────────

@pytest_asyncio.fixture
async def db():
    """In-memory SQLite database for tests."""
    from nexusai.storage.database import Database
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.initialize()
    yield database
    await database.close()


@pytest_asyncio.fixture
async def db_session(db):
    """Single database session for a test."""
    async with db.session() as session:
        yield session


# ── Config Fixture ───────────────────────────────────────────────

@pytest.fixture
def config_dir(tmp_path):
    """Create a minimal config directory for testing."""
    config = tmp_path / "config"
    config.mkdir()
    default = config / "default.yaml"
    default.write_text("""
app:
  name: "NexusAI Test"
  debug: true

storage:
  database_url: "sqlite+aiosqlite:///:memory:"

features:
  dashboard:
    enabled: true
    host: "127.0.0.1"
    port: 8080
    jwt_secret: "test-secret-key-for-testing-only"
    admin_username: "admin"
    admin_password: "testpassword"
  replay_debug:
    enabled: false
  knowledge_base:
    enabled: false
  workflows:
    enabled: false
  scheduler:
    enabled: false
  notifications:
    enabled: false
  mcp:
    enabled: false
  company:
    enabled: false

platforms:
  telegram:
    enabled: false
  discord:
    enabled: false
  slack:
    enabled: false
  cli:
    enabled: false

providers:
  claude_api:
    enabled: false
  openai:
    enabled: false
  ollama:
    enabled: false
""")
    return config


@pytest.fixture
def nexus_config(config_dir):
    from nexusai.core.config import NexusConfig
    return NexusConfig(str(config_dir))


# ── Company Fixtures ─────────────────────────────────────────────

@pytest_asyncio.fixture
async def company_store():
    from nexusai.company.store import CompanyStore
    store = CompanyStore()
    return store


@pytest_asyncio.fixture
async def company_manager(event_bus, agent_engine):
    from nexusai.company.manager import CompanyManager
    manager = CompanyManager(
        event_bus=event_bus,
        agent_engine=agent_engine,
    )
    return manager


# ── Helpers ──────────────────────────────────────────────────────

def make_task(description: str = "test task", user_id: str = "u1") -> TaskRequest:
    return TaskRequest(
        task_id=f"task-{id(description)}",
        description=description,
        user_id=user_id,
        platform="test",
        channel_id="ch1",
    )
