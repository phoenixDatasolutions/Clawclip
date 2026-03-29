"""Ollama Provider — local models via Ollama REST API."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator
from typing import Any

import httpx

from nexusai.core.enums import ModelCapability
from nexusai.core.events import EventBus
from nexusai.core.types import (
    LLMMessage,
    LLMResponse,
    LLMStreamEvent,
    ModelInfo,
    ToolDefinition,
    UsageStats,
)
from nexusai.providers.base import BaseLLMProvider

logger = logging.getLogger(__name__)


class OllamaProvider(BaseLLMProvider):
    """LLM provider using local Ollama models via REST API."""

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        default_model: str = "llama3.1",
        event_bus: EventBus | None = None,
    ) -> None:
        super().__init__("ollama", event_bus=event_bus)
        self._base_url = base_url.rstrip("/")
        self._default_model = default_model

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
        model = model or self._default_model
        api_messages = self._convert_messages(messages, system_prompt)

        payload: dict[str, Any] = {
            "model": model,
            "messages": api_messages,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        if stop_sequences:
            payload["options"]["stop"] = stop_sequences

        async with httpx.AsyncClient(timeout=300) as client:
            resp = await client.post(f"{self._base_url}/api/chat", json=payload)
            resp.raise_for_status()
            data = resp.json()

        content = data.get("message", {}).get("content", "")
        input_tokens = data.get("prompt_eval_count", 0)
        output_tokens = data.get("eval_count", 0)

        return LLMResponse(
            content=content,
            model=model,
            provider=self._name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=0.0,  # Local models are free
            stop_reason="stop",
            raw=data,
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
        model = model or self._default_model
        api_messages = self._convert_messages(messages, system_prompt)

        payload: dict[str, Any] = {
            "model": model,
            "messages": api_messages,
            "stream": True,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }

        async with httpx.AsyncClient(timeout=300) as client:
            async with client.stream("POST", f"{self._base_url}/api/chat", json=payload) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    data = json.loads(line)

                    if data.get("done"):
                        yield LLMStreamEvent(
                            event_type="message_stop",
                            usage=UsageStats(
                                input_tokens=data.get("prompt_eval_count", 0),
                                output_tokens=data.get("eval_count", 0),
                            ),
                        )
                    else:
                        content = data.get("message", {}).get("content", "")
                        if content:
                            yield LLMStreamEvent(
                                event_type="text_delta",
                                text=content,
                            )

    async def list_models(self) -> list[ModelInfo]:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{self._base_url}/api/tags")
                resp.raise_for_status()
                data = resp.json()
            return [
                ModelInfo(
                    model_id=m["name"],
                    provider="ollama",
                    display_name=m["name"],
                    context_window=m.get("details", {}).get("context_length", 4096),
                    max_output_tokens=4096,
                    capabilities=(
                        ModelCapability.TEXT_GENERATION | ModelCapability.STREAMING
                    ).value,
                )
                for m in data.get("models", [])
            ]
        except Exception:
            logger.warning("Failed to list Ollama models")
            return []

    def get_model_capabilities(self, model_id: str) -> int:
        return (ModelCapability.TEXT_GENERATION | ModelCapability.STREAMING).value

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{self._base_url}/api/tags")
                return resp.status_code == 200
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
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            api_messages.append({"role": msg.role, "content": content})
        return api_messages
