"""Claude CLI Provider — wraps the Claude CLI as a subprocess.

Refactored from the bridge pattern, adapted to the BaseLLMProvider interface.
Runs `claude -p "<prompt>" --output-format stream-json` and parses the output.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from typing import Any
from uuid import uuid4

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

logger = logging.getLogger(__name__)


class ClaudeCLIProvider(BaseLLMProvider):
    """LLM provider that invokes the Claude CLI as a subprocess.

    Supports:
    - Text generation (streaming and non-streaming)
    - Session management (--resume / --session-id)
    - Configurable working directory and allowed tools
    - Skip permissions mode
    - Cost tracking from CLI result metadata
    """

    def __init__(
        self,
        default_model: str = "claude-sonnet-4-20250514",
        working_directory: str | None = None,
        allowed_tools: list[str] | None = None,
        skip_permissions: bool = False,
        session_id: str | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        super().__init__("claude_cli", event_bus=event_bus)
        self._default_model = default_model
        self._working_directory = working_directory
        self._allowed_tools = allowed_tools
        self._skip_permissions = skip_permissions
        self._session_id = session_id
        self._active_processes: dict[str, asyncio.subprocess.Process] = {}

    def _build_command(
        self,
        prompt: str,
        model: str,
        *,
        session_id: str | None = None,
    ) -> list[str]:
        """Build the Claude CLI command arguments."""
        cmd = [
            "claude",
            "-p", prompt,
            "--output-format", "stream-json",
            "--verbose",
        ]

        if model:
            cmd.extend(["--model", model])

        if self._skip_permissions:
            cmd.append("--dangerously-skip-permissions")

        effective_session = session_id or self._session_id
        if effective_session:
            cmd.extend(["--resume", effective_session])

        if self._allowed_tools:
            cmd.extend(["--allowedTools"] + self._allowed_tools)

        return cmd

    @staticmethod
    def _messages_to_prompt(
        messages: list[LLMMessage],
        system_prompt: str | None = None,
    ) -> str:
        """Flatten a list of LLMMessages into a single prompt string for the CLI."""
        parts: list[str] = []

        if system_prompt:
            parts.append(f"[System]\n{system_prompt}\n")

        for msg in messages:
            text = msg.content if isinstance(msg.content, str) else json.dumps(msg.content)
            if msg.role == "system":
                parts.append(f"[System]\n{text}")
            elif msg.role == "user":
                parts.append(f"[User]\n{text}")
            elif msg.role == "assistant":
                parts.append(f"[Assistant]\n{text}")
            elif msg.role == "tool":
                parts.append(f"[Tool Result ({msg.name or msg.tool_call_id or 'tool'})]\n{text}")

        return "\n\n".join(parts)

    @staticmethod
    def _parse_stream_event(data: dict[str, Any]) -> LLMStreamEvent | None:
        """Parse a single JSON line from Claude CLI stream-json output into an LLMStreamEvent."""
        msg_type = data.get("type")

        # Stream events (deltas, tool use, etc.)
        if msg_type == "stream_event":
            inner = data.get("event", {})
            inner_type = inner.get("type")

            if inner_type == "content_block_delta":
                delta = inner.get("delta", {})
                delta_type = delta.get("type")

                if delta_type == "text_delta":
                    return LLMStreamEvent(
                        event_type="text_delta",
                        text=delta.get("text", ""),
                    )
                if delta_type == "input_json_delta":
                    return LLMStreamEvent(
                        event_type="tool_input_delta",
                        text=delta.get("partial_json", ""),
                    )

            if inner_type == "content_block_start":
                block = inner.get("content_block", {})
                if block.get("type") == "tool_use":
                    return LLMStreamEvent(
                        event_type="tool_use_start",
                        tool_name=block.get("name"),
                        tool_call_id=block.get("id"),
                    )

            if inner_type == "message_delta":
                delta = inner.get("delta", {})
                if "stop_reason" in delta:
                    return LLMStreamEvent(event_type="message_stop")

        # Final result event — contains usage, cost, session info
        if msg_type == "result":
            return LLMStreamEvent(
                event_type="result",
                text=data.get("result", ""),
                usage=UsageStats(
                    input_tokens=data.get("input_tokens", 0),
                    output_tokens=data.get("output_tokens", 0),
                    total_tokens=data.get("input_tokens", 0) + data.get("output_tokens", 0),
                    cost_usd=data.get("total_cost_usd", 0.0),
                ),
            )

        return None

    async def _run_cli_streaming(
        self,
        prompt: str,
        model: str,
        *,
        session_id: str | None = None,
    ) -> AsyncGenerator[tuple[LLMStreamEvent | None, dict[str, Any]], None]:
        """Run the CLI subprocess and yield (parsed_event, raw_data) tuples."""
        task_id = str(uuid4())
        cmd = self._build_command(prompt, model, session_id=session_id)

        logger.info(
            "Claude CLI subprocess start: task_id=%s, model=%s, cwd=%s",
            task_id, model, self._working_directory,
        )

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self._working_directory,
        )
        self._active_processes[task_id] = proc

        try:
            assert proc.stdout is not None
            async for raw_line in proc.stdout:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    event = self._parse_stream_event(data)
                    yield event, data
                except json.JSONDecodeError:
                    continue

            await proc.wait()

            if proc.returncode and proc.returncode != 0:
                assert proc.stderr is not None
                stderr = await proc.stderr.read()
                err_text = stderr.decode("utf-8", errors="replace").strip()
                if err_text:
                    yield (
                        LLMStreamEvent(
                            event_type="error",
                            text=f"Claude CLI error (exit {proc.returncode}): {err_text[:2000]}",
                        ),
                        {"type": "error", "text": err_text},
                    )
        finally:
            self._active_processes.pop(task_id, None)
            if proc.returncode is None:
                try:
                    proc.kill()
                    await proc.wait()
                except ProcessLookupError:
                    pass

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
        session_id = kwargs.get("session_id")
        prompt = self._messages_to_prompt(messages, system_prompt)

        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        result_data: dict[str, Any] = {}
        current_tool_name: str | None = None
        current_tool_id: str | None = None
        current_tool_input: list[str] = []

        async for event, raw in self._run_cli_streaming(prompt, model, session_id=session_id):
            if event is None:
                continue

            if event.event_type == "text_delta" and event.text:
                text_parts.append(event.text)
            elif event.event_type == "tool_use_start":
                # Flush any previous tool
                if current_tool_name:
                    tool_calls.append(self._build_tool_call(
                        current_tool_id, current_tool_name, current_tool_input,
                    ))
                current_tool_name = event.tool_name
                current_tool_id = event.tool_call_id
                current_tool_input = []
            elif event.event_type == "tool_input_delta" and event.text:
                current_tool_input.append(event.text)
            elif event.event_type == "result":
                result_data = raw
            elif event.event_type == "error":
                raise RuntimeError(event.text or "Claude CLI error")

        # Flush last tool
        if current_tool_name:
            tool_calls.append(self._build_tool_call(
                current_tool_id, current_tool_name, current_tool_input,
            ))

        input_tokens = result_data.get("input_tokens", 0)
        output_tokens = result_data.get("output_tokens", 0)
        cost_usd = result_data.get("total_cost_usd", 0.0)
        result_text = result_data.get("result", "")

        return LLMResponse(
            content=result_text or "".join(text_parts),
            model=result_data.get("model", model),
            provider=self._name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
            stop_reason=result_data.get("stop_reason", "end_turn"),
            tool_calls=tool_calls,
            raw={
                "session_id": result_data.get("session_id", ""),
                "num_turns": result_data.get("num_turns", 0),
                "duration_ms": result_data.get("duration_ms", 0),
            },
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
        session_id = kwargs.get("session_id")
        prompt = self._messages_to_prompt(messages, system_prompt)

        async for event, raw in self._run_cli_streaming(prompt, model, session_id=session_id):
            if event is None:
                continue

            # For the result event, emit it as a message_stop with usage
            if event.event_type == "result":
                yield LLMStreamEvent(
                    event_type="message_stop",
                    usage=event.usage,
                )
            else:
                yield event

    async def list_models(self) -> list[ModelInfo]:
        """Return known Claude models available via CLI."""
        return [
            ModelInfo(
                model_id="claude-opus-4-20250514",
                provider="claude_cli",
                display_name="Claude Opus 4 (CLI)",
                context_window=200_000,
                max_output_tokens=32_000,
                capabilities=(
                    ModelCapability.TEXT_GENERATION | ModelCapability.STREAMING
                    | ModelCapability.TOOL_USE | ModelCapability.VISION
                    | ModelCapability.LONG_CONTEXT | ModelCapability.CODE_EXECUTION
                ).value,
            ),
            ModelInfo(
                model_id="claude-sonnet-4-20250514",
                provider="claude_cli",
                display_name="Claude Sonnet 4 (CLI)",
                context_window=200_000,
                max_output_tokens=16_000,
                capabilities=(
                    ModelCapability.TEXT_GENERATION | ModelCapability.STREAMING
                    | ModelCapability.TOOL_USE | ModelCapability.VISION
                    | ModelCapability.LONG_CONTEXT | ModelCapability.CODE_EXECUTION
                ).value,
            ),
            ModelInfo(
                model_id="claude-haiku-4-20250514",
                provider="claude_cli",
                display_name="Claude Haiku 4 (CLI)",
                context_window=200_000,
                max_output_tokens=8_000,
                capabilities=(
                    ModelCapability.TEXT_GENERATION | ModelCapability.STREAMING
                    | ModelCapability.TOOL_USE | ModelCapability.VISION
                    | ModelCapability.LONG_CONTEXT
                ).value,
            ),
        ]

    def get_model_capabilities(self, model_id: str) -> int:
        return (
            ModelCapability.TEXT_GENERATION | ModelCapability.STREAMING
            | ModelCapability.TOOL_USE | ModelCapability.CODE_EXECUTION
        ).value

    def estimate_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        # Cost is tracked from CLI result metadata directly; use registry as fallback
        from nexusai.providers.model_registry import estimate_cost as registry_cost
        return registry_cost(model, input_tokens, output_tokens)

    async def health_check(self) -> bool:
        """Check if Claude CLI is installed and reachable."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "claude", "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
            return proc.returncode == 0
        except Exception:
            return False

    def cancel_all(self) -> int:
        """Kill all running Claude CLI processes. Returns count killed."""
        count = 0
        for proc in self._active_processes.values():
            if proc.returncode is None:
                proc.kill()
                count += 1
        return count

    @property
    def active_count(self) -> int:
        """Number of currently running CLI subprocesses."""
        return sum(1 for p in self._active_processes.values() if p.returncode is None)

    @staticmethod
    def _build_tool_call(
        tool_id: str | None,
        tool_name: str,
        input_parts: list[str],
    ) -> ToolCall:
        """Assemble a ToolCall from accumulated streaming parts."""
        raw_input = "".join(input_parts)
        try:
            arguments = json.loads(raw_input) if raw_input else {}
        except json.JSONDecodeError:
            arguments = {"raw_input": raw_input}

        return ToolCall(
            id=tool_id or f"call_{tool_name}_{uuid4().hex[:8]}",
            name=tool_name,
            arguments=arguments,
        )
