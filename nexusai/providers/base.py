"""Base LLM Provider — shared logic for all providers (retry, cost tracking, health check)."""

from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from typing import Any

from nexusai.core.events import EventBus, LLMRequestCompleted, LLMRequestStarted
from nexusai.core.types import (
    LLMMessage,
    LLMResponse,
    LLMStreamEvent,
    ModelInfo,
    ToolDefinition,
)

logger = logging.getLogger(__name__)


class BaseLLMProvider(ABC):
    """Base class for LLM providers with shared retry, cost tracking, and health check logic.

    Subclasses implement _generate() and _generate_stream().
    This base handles retries, event emission, and cost tracking.
    """

    def __init__(
        self,
        provider_name: str,
        event_bus: EventBus | None = None,
        max_retries: int = 3,
        retry_base_delay: float = 1.0,
    ) -> None:
        self._name = provider_name
        self._event_bus = event_bus
        self._max_retries = max_retries
        self._retry_base_delay = retry_base_delay

    @property
    def name(self) -> str:
        return self._name

    @abstractmethod
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
        """Provider-specific generation logic."""
        ...

    @abstractmethod
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
        """Provider-specific streaming generation logic."""
        ...
        yield  # pragma: no cover

    async def generate(
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
        """Generate with retry and event emission."""
        conversation_id = kwargs.pop("conversation_id", "")
        start_time = time.monotonic()

        if self._event_bus:
            await self._event_bus.publish(LLMRequestStarted(
                provider=self._name, model=model, conversation_id=conversation_id,
            ))

        last_error: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                response = await self._generate(
                    messages, model,
                    tools=tools, temperature=temperature, max_tokens=max_tokens,
                    stop_sequences=stop_sequences, system_prompt=system_prompt,
                    response_format=response_format, **kwargs,
                )

                if self._event_bus:
                    duration_ms = int((time.monotonic() - start_time) * 1000)
                    await self._event_bus.publish(LLMRequestCompleted(
                        provider=self._name, model=model,
                        conversation_id=conversation_id,
                        input_tokens=response.input_tokens,
                        output_tokens=response.output_tokens,
                        cost_usd=response.cost_usd,
                        duration_ms=duration_ms,
                    ))

                return response

            except Exception as e:
                last_error = e
                if attempt < self._max_retries - 1:
                    delay = self._retry_base_delay * (2 ** attempt)
                    logger.warning(
                        "Provider %s attempt %d failed, retrying in %.1fs: %s",
                        self._name, attempt + 1, delay, e,
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error("Provider %s failed after %d attempts: %s", self._name, self._max_retries, e)

        raise last_error  # type: ignore[misc]

    async def generate_stream(
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
        """Stream with event emission (no retry for streaming)."""
        conversation_id = kwargs.pop("conversation_id", "")
        start_time = time.monotonic()

        if self._event_bus:
            await self._event_bus.publish(LLMRequestStarted(
                provider=self._name, model=model, conversation_id=conversation_id,
            ))

        total_input = 0
        total_output = 0

        async for event in self._generate_stream(
            messages, model,
            tools=tools, temperature=temperature, max_tokens=max_tokens,
            stop_sequences=stop_sequences, system_prompt=system_prompt,
            **kwargs,
        ):
            if event.usage:
                total_input = event.usage.input_tokens
                total_output = event.usage.output_tokens
            yield event

        if self._event_bus:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            cost = self.estimate_cost(model, total_input, total_output)
            await self._event_bus.publish(LLMRequestCompleted(
                provider=self._name, model=model,
                conversation_id=conversation_id,
                input_tokens=total_input, output_tokens=total_output,
                cost_usd=cost, duration_ms=duration_ms,
            ))

    @abstractmethod
    async def list_models(self) -> list[ModelInfo]:
        ...

    @abstractmethod
    def get_model_capabilities(self, model_id: str) -> int:
        ...

    async def count_tokens(self, messages: list[LLMMessage], model: str) -> int:
        """Estimate token count. Override for provider-specific tokenizers."""
        total_chars = sum(
            len(m.content) if isinstance(m.content, str) else sum(len(str(b)) for b in m.content)
            for m in messages
        )
        return total_chars // 4  # Rough estimate

    def estimate_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        """Estimate cost in USD. Override with provider-specific pricing."""
        return 0.0

    async def health_check(self) -> bool:
        """Check if the provider is reachable. Override for actual checks."""
        return True
