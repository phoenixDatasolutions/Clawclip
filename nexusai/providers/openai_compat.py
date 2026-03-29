"""OpenAI-Compatible Provider — works with any OpenAI-compatible API endpoint.

Supports vLLM, Together AI, Groq, Fireworks, Anyscale, and any other
service that implements the OpenAI chat completions API.
"""

from __future__ import annotations

import logging
from typing import Any

from nexusai.core.enums import ModelCapability
from nexusai.core.events import EventBus
from nexusai.core.types import (
    LLMMessage,
    ModelInfo,
)
from nexusai.providers.openai_ import OpenAIProvider

logger = logging.getLogger(__name__)


class OpenAICompatProvider(OpenAIProvider):
    """LLM provider for any OpenAI-compatible API endpoint.

    Extends OpenAIProvider with a configurable base_url, making it work with:
    - vLLM serving endpoints
    - Together AI
    - Groq
    - Fireworks AI
    - Anyscale
    - Any OpenAI-compatible local or remote API

    Usage:
        provider = OpenAICompatProvider(
            base_url="https://api.together.xyz/v1",
            api_key="your-api-key",
            default_model="meta-llama/Llama-3-70b-chat-hf",
        )
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        default_model: str = "",
        event_bus: EventBus | None = None,
    ) -> None:
        # Initialize OpenAIProvider with the custom base_url
        super().__init__(
            api_key=api_key,
            default_model=default_model,
            base_url=base_url,
            event_bus=event_bus,
        )
        # Override the provider name
        self._name = "openai_compat"
        self._compat_base_url = base_url

    async def list_models(self) -> list[ModelInfo]:
        """Try to query the /models endpoint to discover available models."""
        try:
            client = self._get_client()
            models_response = await client.models.list()
            return [
                ModelInfo(
                    model_id=m.id,
                    provider="openai_compat",
                    display_name=m.id,
                    context_window=getattr(m, "context_window", 4096),
                    max_output_tokens=getattr(m, "max_output_tokens", 4096),
                    capabilities=(
                        ModelCapability.TEXT_GENERATION | ModelCapability.STREAMING
                    ).value,
                )
                for m in models_response.data
            ]
        except Exception:
            logger.warning(
                "Failed to list models from OpenAI-compatible endpoint: %s",
                self._compat_base_url,
            )
            return []

    def get_model_capabilities(self, model_id: str) -> int:
        """Return basic capabilities — the actual capabilities depend on the endpoint."""
        return (
            ModelCapability.TEXT_GENERATION | ModelCapability.STREAMING
        ).value

    def estimate_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        """Cost estimation is not available for arbitrary endpoints."""
        return 0.0

    async def health_check(self) -> bool:
        """Check if the endpoint is reachable by listing models."""
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
        """Use parent's message conversion — OpenAI-compatible format."""
        return OpenAIProvider._convert_messages(messages, system_prompt)
