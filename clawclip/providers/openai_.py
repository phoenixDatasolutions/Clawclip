"""OpenAI Provider — uses the openai Python SDK."""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from typing import Any

from clawclip.core.enums import ModelCapability
from clawclip.core.events import EventBus
from clawclip.core.types import (
    LLMMessage,
    LLMResponse,
    LLMStreamEvent,
    ModelInfo,
    ToolCall,
    ToolDefinition,
    UsageStats,
)
from clawclip.providers.base import BaseLLMProvider
from clawclip.providers.model_registry import estimate_cost, get_models_for_provider

logger = logging.getLogger(__name__)


class OpenAIProvider(BaseLLMProvider):
    """LLM provider using the OpenAI API."""

    def __init__(
        self,
        api_key: str,
        default_model: str = "gpt-4o",
        organization: str = "",
        base_url: str | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        super().__init__("openai", event_bus=event_bus)
        self._api_key = api_key
        self._default_model = default_model
        self._organization = organization
        self._base_url = base_url
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                import openai
                kwargs: dict[str, Any] = {"api_key": self._api_key}
                if self._organization:
                    kwargs["organization"] = self._organization
                if self._base_url:
                    kwargs["base_url"] = self._base_url
                self._client = openai.AsyncOpenAI(**kwargs)
            except ImportError:
                raise ImportError(
                    "openai package not installed. Install with: pip install clawclip[openai]"
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

        api_messages = self._convert_messages(messages, system_prompt)

        api_kwargs: dict[str, Any] = {
            "model": model,
            "messages": api_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if stop_sequences:
            api_kwargs["stop"] = stop_sequences
        if tools:
            api_kwargs["tools"] = self._convert_tools(tools)
        if response_format:
            api_kwargs["response_format"] = response_format

        response = await client.chat.completions.create(**api_kwargs)
        choice = response.choices[0]

        content = choice.message.content or ""
        tool_calls: list[ToolCall] = []
        if choice.message.tool_calls:
            import json
            for tc in choice.message.tool_calls:
                tool_calls.append(ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=json.loads(tc.function.arguments),
                ))

        usage = response.usage
        input_tokens = usage.prompt_tokens if usage else 0
        output_tokens = usage.completion_tokens if usage else 0
        cost = estimate_cost(model, input_tokens, output_tokens)

        return LLMResponse(
            content=content,
            model=model,
            provider=self._name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            stop_reason=choice.finish_reason or "stop",
            tool_calls=tool_calls,
            raw={"id": response.id},
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

        api_messages = self._convert_messages(messages, system_prompt)

        api_kwargs: dict[str, Any] = {
            "model": model,
            "messages": api_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if stop_sequences:
            api_kwargs["stop"] = stop_sequences
        if tools:
            api_kwargs["tools"] = self._convert_tools(tools)

        stream = await client.chat.completions.create(**api_kwargs)

        async for chunk in stream:
            if not chunk.choices:
                if chunk.usage:
                    yield LLMStreamEvent(
                        event_type="message_stop",
                        usage=UsageStats(
                            input_tokens=chunk.usage.prompt_tokens,
                            output_tokens=chunk.usage.completion_tokens,
                            total_tokens=chunk.usage.total_tokens,
                            cost_usd=estimate_cost(
                                model, chunk.usage.prompt_tokens, chunk.usage.completion_tokens
                            ),
                        ),
                    )
                continue

            delta = chunk.choices[0].delta
            if delta.content:
                yield LLMStreamEvent(event_type="text_delta", text=delta.content)
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    if tc.function and tc.function.name:
                        yield LLMStreamEvent(
                            event_type="tool_use_start",
                            tool_name=tc.function.name,
                            tool_call_id=tc.id,
                        )
                    if tc.function and tc.function.arguments:
                        yield LLMStreamEvent(
                            event_type="tool_input_delta",
                            text=tc.function.arguments,
                        )

    async def list_models(self) -> list[ModelInfo]:
        return get_models_for_provider("openai")

    def get_model_capabilities(self, model_id: str) -> int:
        from clawclip.providers.model_registry import get_model_info
        info = get_model_info(model_id)
        return info.capabilities if info else (
            ModelCapability.TEXT_GENERATION | ModelCapability.STREAMING | ModelCapability.TOOL_USE
        ).value

    def estimate_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        return estimate_cost(model, input_tokens, output_tokens)

    async def health_check(self) -> bool:
        try:
            client = self._get_client()
            await client.models.list()
            return True
        except Exception:
            return False

    @staticmethod
    def _convert_messages(
        messages: list[LLMMessage], system_prompt: str | None = None
    ) -> list[dict[str, Any]]:
        api_messages: list[dict[str, Any]] = []
        if system_prompt:
            api_messages.append({"role": "system", "content": system_prompt})
        for msg in messages:
            api_msg: dict[str, Any] = {"role": msg.role, "content": msg.content}
            if msg.role == "tool" and msg.tool_call_id:
                api_msg["tool_call_id"] = msg.tool_call_id
            api_messages.append(api_msg)
        return api_messages

    @staticmethod
    def _convert_tools(tools: list[ToolDefinition]) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                },
            }
            for tool in tools
        ]
