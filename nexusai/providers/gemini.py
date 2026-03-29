"""Gemini Provider — uses the google-generativeai SDK."""

from __future__ import annotations

import json
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


class GeminiProvider(BaseLLMProvider):
    """LLM provider using the Google Gemini API (google-generativeai SDK).

    Supports:
    - Text generation (streaming and non-streaming)
    - Tool/function calling via function_declarations
    - Vision (images in messages)
    - Cost tracking via model registry
    """

    def __init__(
        self,
        api_key: str,
        default_model: str = "gemini-2.5-pro",
        event_bus: EventBus | None = None,
    ) -> None:
        super().__init__("gemini", event_bus=event_bus)
        self._api_key = api_key
        self._default_model = default_model
        self._genai: Any = None

    def _get_genai(self) -> Any:
        """Lazy-init the google-generativeai module and configure API key."""
        if self._genai is None:
            try:
                import google.generativeai as genai
                genai.configure(api_key=self._api_key)
                self._genai = genai
            except ImportError:
                raise ImportError(
                    "google-generativeai package not installed. "
                    "Install with: pip install nexusai[gemini]"
                )
        return self._genai

    def _build_model(
        self,
        model: str,
        *,
        tools: list[ToolDefinition] | None = None,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> Any:
        """Create a GenerativeModel instance with the given configuration."""
        genai = self._get_genai()

        generation_config = genai.types.GenerationConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
        )

        model_kwargs: dict[str, Any] = {
            "model_name": model,
            "generation_config": generation_config,
        }

        if system_prompt:
            model_kwargs["system_instruction"] = system_prompt

        if tools:
            model_kwargs["tools"] = [self._convert_tools(tools)]

        return genai.GenerativeModel(**model_kwargs)

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

        gemini_model = self._build_model(
            model,
            tools=tools,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        contents = self._convert_messages(messages)

        response = await gemini_model.generate_content_async(contents)

        # Parse response
        content = ""
        tool_calls: list[ToolCall] = []

        for candidate in response.candidates:
            for part in candidate.content.parts:
                if hasattr(part, "text") and part.text:
                    content += part.text
                elif hasattr(part, "function_call") and part.function_call:
                    fc = part.function_call
                    tool_calls.append(ToolCall(
                        id=f"call_{fc.name}_{id(fc)}",
                        name=fc.name,
                        arguments=dict(fc.args) if fc.args else {},
                    ))

        # Extract usage
        usage = response.usage_metadata
        input_tokens = getattr(usage, "prompt_token_count", 0)
        output_tokens = getattr(usage, "candidates_token_count", 0)
        cost = estimate_cost(model, input_tokens, output_tokens)

        # Determine stop reason
        stop_reason = "end_turn"
        if tool_calls:
            stop_reason = "tool_use"
        elif hasattr(response.candidates[0], "finish_reason"):
            finish = response.candidates[0].finish_reason
            if finish is not None:
                stop_reason = str(finish).lower()

        return LLMResponse(
            content=content,
            model=model,
            provider=self._name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            stop_reason=stop_reason,
            tool_calls=tool_calls,
            raw={"candidates_count": len(response.candidates)},
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

        gemini_model = self._build_model(
            model,
            tools=tools,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        contents = self._convert_messages(messages)

        response = await gemini_model.generate_content_async(contents, stream=True)

        input_tokens = 0
        output_tokens = 0

        async for chunk in response:
            # Extract usage if available
            if hasattr(chunk, "usage_metadata") and chunk.usage_metadata:
                input_tokens = getattr(chunk.usage_metadata, "prompt_token_count", 0)
                output_tokens = getattr(chunk.usage_metadata, "candidates_token_count", 0)

            if not chunk.candidates:
                continue

            for part in chunk.candidates[0].content.parts:
                if hasattr(part, "text") and part.text:
                    yield LLMStreamEvent(
                        event_type="text_delta",
                        text=part.text,
                    )
                elif hasattr(part, "function_call") and part.function_call:
                    fc = part.function_call
                    yield LLMStreamEvent(
                        event_type="tool_use_start",
                        tool_name=fc.name,
                        tool_call_id=f"call_{fc.name}_{id(fc)}",
                    )
                    if fc.args:
                        yield LLMStreamEvent(
                            event_type="tool_input_delta",
                            text=json.dumps(dict(fc.args)),
                        )

        # Final usage event
        cost = estimate_cost(model, input_tokens, output_tokens)
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
        return get_models_for_provider("gemini")

    def get_model_capabilities(self, model_id: str) -> int:
        from nexusai.providers.model_registry import get_model_info
        info = get_model_info(model_id)
        if info:
            return info.capabilities
        return (
            ModelCapability.TEXT_GENERATION | ModelCapability.STREAMING
            | ModelCapability.TOOL_USE | ModelCapability.VISION
        ).value

    def estimate_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        return estimate_cost(model, input_tokens, output_tokens)

    async def health_check(self) -> bool:
        try:
            genai = self._get_genai()
            # Verify the SDK is configured and we can list models
            models = genai.list_models()
            return any(True for _ in models)
        except Exception:
            return False

    @staticmethod
    def _convert_messages(messages: list[LLMMessage]) -> list[Any]:
        """Convert NexusAI messages to Gemini Content format.

        Gemini expects a list of Content objects with role 'user' or 'model'.
        System messages are handled separately via system_instruction.
        Tool results are sent as Part objects with function_response.
        """
        try:
            from google.generativeai import types as genai_types
        except ImportError:
            raise ImportError("google-generativeai package not installed.")

        contents: list[Any] = []

        for msg in messages:
            if msg.role == "system":
                continue  # Handled via system_instruction

            # Map roles
            if msg.role == "assistant":
                role = "model"
            elif msg.role == "tool":
                # Tool results go as function_response parts
                text = msg.content if isinstance(msg.content, str) else json.dumps(msg.content)
                part = genai_types.Part(
                    function_response=genai_types.FunctionResponse(
                        name=msg.name or "tool",
                        response={"result": text},
                    )
                )
                contents.append(genai_types.Content(role="function", parts=[part]))
                continue
            else:
                role = "user"

            # Build parts
            parts: list[Any] = []
            if isinstance(msg.content, str):
                parts.append(genai_types.Part(text=msg.content))
            elif isinstance(msg.content, list):
                for block in msg.content:
                    if isinstance(block, dict):
                        if block.get("type") == "text":
                            parts.append(genai_types.Part(text=block["text"]))
                        elif block.get("type") == "image_url":
                            # Inline image data
                            url = block.get("image_url", {}).get("url", "")
                            if url.startswith("data:"):
                                # Base64 encoded
                                import base64
                                header, b64data = url.split(",", 1)
                                mime = header.split(":")[1].split(";")[0]
                                parts.append(genai_types.Part(
                                    inline_data=genai_types.Blob(
                                        mime_type=mime,
                                        data=base64.b64decode(b64data),
                                    )
                                ))
                            else:
                                parts.append(genai_types.Part(text=f"[Image: {url}]"))
                    else:
                        parts.append(genai_types.Part(text=str(block)))

            if parts:
                contents.append(genai_types.Content(role=role, parts=parts))

        return contents

    @staticmethod
    def _convert_tools(tools: list[ToolDefinition]) -> Any:
        """Convert NexusAI tool definitions to Gemini function_declarations."""
        try:
            from google.generativeai import types as genai_types
        except ImportError:
            raise ImportError("google-generativeai package not installed.")

        declarations = []
        for tool in tools:
            # Clean up the JSON schema for Gemini compatibility
            params = dict(tool.parameters) if tool.parameters else {}
            # Gemini expects a subset of JSON Schema; remove unsupported keys
            params.pop("additionalProperties", None)

            declarations.append(genai_types.FunctionDeclaration(
                name=tool.name,
                description=tool.description,
                parameters=params if params else None,
            ))

        return genai_types.Tool(function_declarations=declarations)
