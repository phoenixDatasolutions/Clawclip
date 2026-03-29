"""LiteLLM Provider — thin wrapper around the litellm library.

Supports 100+ LLM models through a unified interface.
"""

from __future__ import annotations

import json
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

logger = logging.getLogger(__name__)


class LiteLLMProvider(BaseLLMProvider):
    """LLM provider using the litellm library for universal model access.

    Supports:
    - Any model litellm supports (OpenAI, Anthropic, Cohere, Replicate, etc.)
    - Text generation (streaming and non-streaming)
    - Tool/function calling (where supported by the underlying model)
    - Cost estimation via litellm.completion_cost()
    - Pass-through for all litellm parameters
    """

    def __init__(
        self,
        default_model: str = "gpt-4o",
        api_key: str | None = None,
        event_bus: EventBus | None = None,
        **litellm_kwargs: Any,
    ) -> None:
        super().__init__("litellm", event_bus=event_bus)
        self._default_model = default_model
        self._api_key = api_key
        self._litellm_kwargs = litellm_kwargs
        self._litellm: Any = None

    def _get_litellm(self) -> Any:
        """Lazy-init the litellm module."""
        if self._litellm is None:
            try:
                import litellm
                # Suppress litellm's own logging unless debug
                litellm.suppress_debug_info = True
                if self._api_key:
                    litellm.api_key = self._api_key
                self._litellm = litellm
            except ImportError:
                raise ImportError(
                    "litellm package not installed. "
                    "Install with: pip install clawclip[litellm]"
                )
        return self._litellm

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
        litellm = self._get_litellm()
        model = model or self._default_model

        api_messages = self._convert_messages(messages, system_prompt)

        api_kwargs: dict[str, Any] = {
            "model": model,
            "messages": api_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            **self._litellm_kwargs,
            **kwargs,
        }
        if stop_sequences:
            api_kwargs["stop"] = stop_sequences
        if tools:
            api_kwargs["tools"] = self._convert_tools(tools)
        if response_format:
            api_kwargs["response_format"] = response_format

        response = await litellm.acompletion(**api_kwargs)
        choice = response.choices[0]

        content = choice.message.content or ""
        tool_calls: list[ToolCall] = []
        if choice.message.tool_calls:
            for tc in choice.message.tool_calls:
                tool_calls.append(ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=json.loads(tc.function.arguments)
                    if isinstance(tc.function.arguments, str)
                    else tc.function.arguments,
                ))

        # Token usage
        usage = response.usage
        input_tokens = getattr(usage, "prompt_tokens", 0) if usage else 0
        output_tokens = getattr(usage, "completion_tokens", 0) if usage else 0

        # Cost via litellm
        cost = self._compute_cost(response)

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
        litellm = self._get_litellm()
        model = model or self._default_model

        api_messages = self._convert_messages(messages, system_prompt)

        api_kwargs: dict[str, Any] = {
            "model": model,
            "messages": api_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
            **self._litellm_kwargs,
            **kwargs,
        }
        if stop_sequences:
            api_kwargs["stop"] = stop_sequences
        if tools:
            api_kwargs["tools"] = self._convert_tools(tools)

        response = await litellm.acompletion(**api_kwargs)

        input_tokens = 0
        output_tokens = 0

        async for chunk in response:
            # Some providers include usage in stream chunks
            if hasattr(chunk, "usage") and chunk.usage:
                input_tokens = getattr(chunk.usage, "prompt_tokens", 0)
                output_tokens = getattr(chunk.usage, "completion_tokens", 0)

            if not chunk.choices:
                continue

            delta = chunk.choices[0].delta

            # Text content
            if hasattr(delta, "content") and delta.content:
                yield LLMStreamEvent(event_type="text_delta", text=delta.content)

            # Tool calls
            if hasattr(delta, "tool_calls") and delta.tool_calls:
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

            # Finish reason
            finish_reason = getattr(chunk.choices[0], "finish_reason", None)
            if finish_reason:
                cost = self.estimate_cost(model, input_tokens, output_tokens)
                yield LLMStreamEvent(
                    event_type="message_stop",
                    usage=UsageStats(
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        total_tokens=input_tokens + output_tokens,
                        cost_usd=cost,
                    ),
                )

    async def list_models(self) -> list[ModelInfo]:
        """Return empty list — litellm supports too many models to enumerate."""
        return []

    def get_model_capabilities(self, model_id: str) -> int:
        """Return a reasonable default set of capabilities."""
        return (
            ModelCapability.TEXT_GENERATION | ModelCapability.STREAMING
        ).value

    def estimate_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        """Estimate cost using litellm's built-in cost tracking."""
        try:
            litellm = self._get_litellm()
            return litellm.completion_cost(
                model=model,
                prompt_tokens=input_tokens,
                completion_tokens=output_tokens,
            )
        except Exception:
            return 0.0

    async def health_check(self) -> bool:
        """Check that litellm is importable and configured."""
        try:
            self._get_litellm()
            return True
        except Exception:
            return False

    def _compute_cost(self, response: Any) -> float:
        """Compute cost from a litellm response object."""
        try:
            litellm = self._get_litellm()
            return litellm.completion_cost(completion_response=response)
        except Exception:
            return 0.0

    @staticmethod
    def _convert_messages(
        messages: list[LLMMessage], system_prompt: str | None = None
    ) -> list[dict[str, Any]]:
        """Convert ClawClip messages to the OpenAI-compatible format litellm expects."""
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
        """Convert ClawClip tool definitions to OpenAI function-calling format."""
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
