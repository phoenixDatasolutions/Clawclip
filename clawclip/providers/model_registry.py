"""Model Registry — metadata, pricing, and capabilities for known LLM models."""

from __future__ import annotations

from clawclip.core.enums import ModelCapability
from clawclip.core.types import ModelInfo

# Pricing per 1K tokens in USD (as of early 2026)
KNOWN_MODELS: dict[str, ModelInfo] = {
    # ── Claude (Anthropic) ──────────────────────────────────────
    "claude-opus-4-20250514": ModelInfo(
        model_id="claude-opus-4-20250514",
        provider="claude_api",
        display_name="Claude Opus 4",
        context_window=200_000,
        max_output_tokens=32_000,
        capabilities=(
            ModelCapability.TEXT_GENERATION | ModelCapability.STREAMING
            | ModelCapability.TOOL_USE | ModelCapability.VISION
            | ModelCapability.LONG_CONTEXT | ModelCapability.CODE_EXECUTION
        ).value,
        input_cost_per_1k=0.015,
        output_cost_per_1k=0.075,
    ),
    "claude-sonnet-4-20250514": ModelInfo(
        model_id="claude-sonnet-4-20250514",
        provider="claude_api",
        display_name="Claude Sonnet 4",
        context_window=200_000,
        max_output_tokens=16_000,
        capabilities=(
            ModelCapability.TEXT_GENERATION | ModelCapability.STREAMING
            | ModelCapability.TOOL_USE | ModelCapability.VISION
            | ModelCapability.LONG_CONTEXT | ModelCapability.CODE_EXECUTION
        ).value,
        input_cost_per_1k=0.003,
        output_cost_per_1k=0.015,
    ),
    "claude-haiku-4-20250514": ModelInfo(
        model_id="claude-haiku-4-20250514",
        provider="claude_api",
        display_name="Claude Haiku 4",
        context_window=200_000,
        max_output_tokens=8_000,
        capabilities=(
            ModelCapability.TEXT_GENERATION | ModelCapability.STREAMING
            | ModelCapability.TOOL_USE | ModelCapability.VISION
            | ModelCapability.LONG_CONTEXT
        ).value,
        input_cost_per_1k=0.0008,
        output_cost_per_1k=0.004,
    ),

    # ── OpenAI ──────────────────────────────────────────────────
    "gpt-4o": ModelInfo(
        model_id="gpt-4o",
        provider="openai",
        display_name="GPT-4o",
        context_window=128_000,
        max_output_tokens=16_384,
        capabilities=(
            ModelCapability.TEXT_GENERATION | ModelCapability.STREAMING
            | ModelCapability.TOOL_USE | ModelCapability.VISION
            | ModelCapability.LONG_CONTEXT | ModelCapability.JSON_MODE
        ).value,
        input_cost_per_1k=0.0025,
        output_cost_per_1k=0.01,
    ),
    "gpt-4o-mini": ModelInfo(
        model_id="gpt-4o-mini",
        provider="openai",
        display_name="GPT-4o Mini",
        context_window=128_000,
        max_output_tokens=16_384,
        capabilities=(
            ModelCapability.TEXT_GENERATION | ModelCapability.STREAMING
            | ModelCapability.TOOL_USE | ModelCapability.VISION
            | ModelCapability.JSON_MODE
        ).value,
        input_cost_per_1k=0.00015,
        output_cost_per_1k=0.0006,
    ),
    "o1": ModelInfo(
        model_id="o1",
        provider="openai",
        display_name="o1",
        context_window=200_000,
        max_output_tokens=100_000,
        capabilities=(
            ModelCapability.TEXT_GENERATION | ModelCapability.STREAMING
            | ModelCapability.TOOL_USE | ModelCapability.VISION
            | ModelCapability.LONG_CONTEXT
        ).value,
        input_cost_per_1k=0.015,
        output_cost_per_1k=0.06,
    ),

    # ── Google Gemini ───────────────────────────────────────────
    "gemini-2.0-flash": ModelInfo(
        model_id="gemini-2.0-flash",
        provider="gemini",
        display_name="Gemini 2.0 Flash",
        context_window=1_000_000,
        max_output_tokens=8_192,
        capabilities=(
            ModelCapability.TEXT_GENERATION | ModelCapability.STREAMING
            | ModelCapability.TOOL_USE | ModelCapability.VISION
            | ModelCapability.LONG_CONTEXT | ModelCapability.JSON_MODE
        ).value,
        input_cost_per_1k=0.0001,
        output_cost_per_1k=0.0004,
    ),
    "gemini-2.5-pro": ModelInfo(
        model_id="gemini-2.5-pro",
        provider="gemini",
        display_name="Gemini 2.5 Pro",
        context_window=1_000_000,
        max_output_tokens=65_536,
        capabilities=(
            ModelCapability.TEXT_GENERATION | ModelCapability.STREAMING
            | ModelCapability.TOOL_USE | ModelCapability.VISION
            | ModelCapability.LONG_CONTEXT | ModelCapability.JSON_MODE
            | ModelCapability.CODE_EXECUTION
        ).value,
        input_cost_per_1k=0.00125,
        output_cost_per_1k=0.01,
    ),
}


def get_model_info(model_id: str) -> ModelInfo | None:
    """Look up model info by ID."""
    return KNOWN_MODELS.get(model_id)


def get_models_for_provider(provider: str) -> list[ModelInfo]:
    """Get all known models for a provider."""
    return [m for m in KNOWN_MODELS.values() if m.provider == provider]


def estimate_cost(model_id: str, input_tokens: int, output_tokens: int) -> float:
    """Estimate cost in USD for a given model and token counts."""
    model = KNOWN_MODELS.get(model_id)
    if model is None:
        return 0.0
    input_cost = (input_tokens / 1000) * model.input_cost_per_1k
    output_cost = (output_tokens / 1000) * model.output_cost_per_1k
    return round(input_cost + output_cost, 6)
