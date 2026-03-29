"""Claude API Provider — uses the Anthropic Python SDK."""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from typing import Any

from nexusai.core.enums import ModelCapability
from nexusai.core.events import EventBus
from nexusai.core.types import (
    LLMMessage,
    LLMResponse,
    LLMStreamEvent,
    ModelInfo,
    ToolCall,
    ToolDefinition,
    UsageStats,
)
from nexusai.providers.base import BaseLLMProvider
from nexusai.providers.model_registry import estimate_cost, get_models_for_provider

logger = logging.getLogger(__name__)


class ClaudeAPIProvider(BaseLLMProvider):
    """LLM provider using the Anthropic API (anthropic SDK).

    Supports:
    - Text generation (streaming and non-streaming)
    - Tool/function calling
    - Vision (images in messages)
    - Cost tracking
    """

    def __init__(
        self,
        api_key: str,
        default_model: str = "claude-sonnet-4-20250514",
        max_tokens: int = 8192,
        event_bus: EventBus | None = None,
    ) -> None:
        super().__init__("claude_api", event_bus=event_bus)
        self._api_key = api_key
        self._default_model = default_model
        self._max_tokens = max_tokens
        self._client: Any = None

    def _get_client(self) -> Any:
        """Lazy-init the Anthropic client."""
        if self._client is None:
            try:
                import anthropic
                self._client = anthropic.AsyncAnthropic(api_key=self._api_key)
            except ImportError:
                raise ImportError(
                    "anthropic package not installed. Install with: pip install nexusai[claude-api]"
                )
        return self._client

    async def _generate(
        self,
        messages: list[LLMMessage],
        model: str,
        *,
        tools: list[ToolDefinition] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        stop_sequences: list[str] | None = None,
        system_prompt: str | None = None,
        response_format: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        client = self._get_client()
        model = model or self._default_model

        # Build API messages
        api_messages = self._convert_messages(messages)

        # Build kwargs
        api_kwargs: dict[str, Any] = {
            "model": model,
            "messages": api_messages,
            "max_tokens": max_tokens or self._max_tokens,
            "temperature": temperature,
        }
        if system_prompt:
            api_kwargs["system"] = system_prompt
        if stop_sequences:
            api_kwargs["stop_sequences"] = stop_sequences
        if tools:
            api_kwargs["tools"] = self._convert_tools(tools)

        response = await client.messages.create(**api_kwargs)

        # Parse response
        content = ""
        tool_calls: list[ToolCall] = []
        for block in response.content:
            if block.type == "text":
                content += block.text
            elif block.type == "tool_use":
                tool_calls.append(ToolCall(
                    id=block.id,
                    name=block.name,
                    arguments=block.input,
                ))

        cost = estimate_cost(model, response.usage.input_tokens, response.usage.output_tokens)

        return LLMResponse(
            content=content,
            model=model,
            provider=self._name,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            cost_usd=cost,
            stop_reason=response.stop_reason or "end_turn",
            tool_calls=tool_calls,
            raw={"id": response.id, "model": response.model},
        )

    async def _generate_stream(
        self,
        messages: list[LLMMessage],
        model: str,
        *,
        tools: list[ToolDefinition] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        stop_sequences: list[str] | None = None,
        system_prompt: str | None = None,
        **kwargs: Any,
    ) -> AsyncGenerator[LLMStreamEvent, None]:
        client = self._get_client()
        model = model or self._default_model

        api_messages = self._convert_messages(messages)

        api_kwargs: dict[str, Any] = {
            "model": model,
            "messages": api_messages,
            "max_tokens": max_tokens or self._max_tokens,
            "temperature": temperature,
        }
        if system_prompt:
            api_kwargs["system"] = system_prompt
        if stop_sequences:
            api_kwargs["stop_sequences"] = stop_sequences
        if tools:
            api_kwargs["tools"] = self._convert_tools(tools)

        async with client.messages.stream(**api_kwargs) as stream:
            async for event in stream:
                if event.type == "content_block_delta":
                    if hasattr(event.delta, "text"):
                        yield LLMStreamEvent(
                            event_type="text_delta",
                            text=event.delta.text,
                        )
                    elif hasattr(event.delta, "partial_json"):
                        yield LLMStreamEvent(
                            event_type="tool_input_delta",
                            text=event.delta.partial_json,
                        )
                elif event.type == "content_block_start":
                    if hasattr(event.content_block, "name"):
                        yield LLMStreamEvent(
                            event_type="tool_use_start",
                            tool_name=event.content_block.name,
                            tool_call_id=event.content_block.id,
                        )
                elif event.type == "message_stop":
                    usage = stream.get_final_message().usage
                    yield LLMStreamEvent(
                        event_type="message_stop",
                        usage=UsageStats(
                            input_tokens=usage.input_tokens,
                            output_tokens=usage.output_tokens,
                            total_tokens=usage.input_tokens + usage.output_tokens,
                            cost_usd=estimate_cost(model, usage.input_tokens, usage.output_tokens),
                        ),
                    )

    async def list_models(self) -> list[ModelInfo]:
        return get_models_for_provider("claude_api")

    def get_model_capabilities(self, model_id: str) -> int:
        from nexusai.providers.model_registry import get_model_info
        info = get_model_info(model_id)
        if info:
            return info.capabilities
        return (ModelCapability.TEXT_GENERATION | ModelCapability.STREAMING | ModelCapability.TOOL_USE).value

    def estimate_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        return estimate_cost(model, input_tokens, output_tokens)

    async def health_check(self) -> bool:
        try:
            client = self._get_client()
            # Simple check — just verify we can create the client
            return client is not None
        except Exception:
            return False

    @staticmethod
    def _convert_messages(messages: list[LLMMessage]) -> list[dict[str, Any]]:
        """Convert NexusAI messages to Anthropic API format."""
        api_messages: list[dict[str, Any]] = []
        for msg in messages:
            if msg.role == "system":
                continue  # System prompt handled separately
            api_msg: dict[str, Any] = {"role": msg.role}
            if isinstance(msg.content, str):
                api_msg["content"] = msg.content
            else:
                api_msg["content"] = msg.content
            if msg.tool_call_id:
                api_msg["content"] = [
                    {"type": "tool_result", "tool_use_id": msg.tool_call_id, "content": msg.content}
                ]
            api_messages.append(api_msg)
        return api_messages

    @staticmethod
    def _convert_tools(tools: list[ToolDefinition]) -> list[dict[str, Any]]:
        """Convert NexusAI tool definitions to Anthropic format."""
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.parameters,
            }
            for tool in tools
        ]
