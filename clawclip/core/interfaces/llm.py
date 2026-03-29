"""LLM Provider protocol — interface every LLM provider must implement."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any, Protocol, runtime_checkable

from clawclip.core.types import (
    LLMMessage,
    LLMResponse,
    LLMStreamEvent,
    ModelInfo,
    ToolDefinition,
)


@runtime_checkable
class LLMProvider(Protocol):
    """Interface every LLM provider must implement.

    Implementations: ClaudeAPIProvider, ClaudeCLIProvider, OpenAIProvider, etc.
    """

    @property
    def name(self) -> str:
        """Provider identifier (e.g., 'claude_api', 'openai')."""
        ...

    async def list_models(self) -> list[ModelInfo]:
        """List available models from this provider."""
        ...

    def get_model_capabilities(self, model_id: str) -> int:
        """Return the ModelCapability flags for a specific model."""
        ...

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
        """Generate a response (non-streaming)."""
        ...

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
        """Generate a streaming response."""
        ...

    async def count_tokens(
        self,
        messages: list[LLMMessage],
        model: str,
    ) -> int:
        """Count tokens for the given messages."""
        ...

    def estimate_cost(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> float:
        """Estimate cost in USD for a given usage."""
        ...

    async def health_check(self) -> bool:
        """Verify the provider is reachable and configured."""
        ...
