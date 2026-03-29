"""NexusAI shared domain types — dataclasses used across all modules."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return str(uuid4())


# ── Platform Types ──────────────────────────────────────────────


@dataclass
class PlatformUser:
    """A user on a specific messaging platform."""
    platform: str
    platform_user_id: str
    username: str | None = None
    display_name: str | None = None


@dataclass
class FileAttachment:
    """A file attached to a message."""
    filename: str
    content: bytes | None = None
    url: str | None = None
    mime_type: str = "application/octet-stream"
    size: int = 0


@dataclass
class ButtonAction:
    """An interactive button in a message."""
    text: str
    callback_data: str
    url: str | None = None


@dataclass
class IncomingMessage:
    """A message received from any platform."""
    platform: str
    channel_id: str
    message_id: str
    user: PlatformUser
    text: str
    attachments: list[FileAttachment] = field(default_factory=list)
    thread_id: str | None = None
    reply_to_id: str | None = None
    timestamp: datetime = field(default_factory=_utcnow)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class OutgoingMessage:
    """A message to send on any platform."""
    text: str
    parse_mode: str | None = None  # html, markdown, plain
    reply_to_id: str | None = None
    thread_id: str | None = None
    attachments: list[FileAttachment] = field(default_factory=list)
    buttons: list[list[ButtonAction]] | None = None


@dataclass
class StreamChunk:
    """A chunk of streaming output."""
    text: str = ""
    tool_name: str | None = None
    is_final: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


# ── LLM Types ───────────────────────────────────────────────────


@dataclass
class LLMMessage:
    """A message in an LLM conversation."""
    role: str  # user, assistant, system, tool
    content: str | list[dict[str, Any]]  # text or multimodal content blocks
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[ToolCall] | None = None


@dataclass
class ToolDefinition:
    """A tool/function definition exposed to an LLM."""
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema
    required_permissions: list[str] = field(default_factory=list)


@dataclass
class ToolCall:
    """An LLM's request to call a tool."""
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ToolResult:
    """The result of a tool call."""
    tool_call_id: str
    output: str
    is_error: bool = False


@dataclass
class UsageStats:
    """Token usage statistics for an LLM call."""
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0


@dataclass
class ModelInfo:
    """Metadata about an LLM model."""
    model_id: str
    provider: str
    display_name: str
    context_window: int
    max_output_tokens: int
    capabilities: int  # ModelCapability flags
    input_cost_per_1k: float = 0.0
    output_cost_per_1k: float = 0.0


@dataclass
class LLMResponse:
    """A complete (non-streaming) LLM response."""
    content: str
    model: str
    provider: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    stop_reason: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class LLMStreamEvent:
    """A single event in a streaming LLM response."""
    event_type: str  # text_delta, tool_use_start, tool_input_delta, message_stop, error
    text: str | None = None
    tool_name: str | None = None
    tool_call_id: str | None = None
    tool_arguments: dict[str, Any] | None = None
    usage: UsageStats | None = None


# ── Agent Types ─────────────────────────────────────────────────


@dataclass
class AgentConfig:
    """Configuration for an agent instance."""
    agent_type: str
    provider: str
    model: str
    system_prompt: str
    allowed_skills: list[str]
    max_turns: int = 50
    temperature: float = 0.7
    max_tokens: int = 4096
    max_delegations: int = 5
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class TaskRequest:
    """A task to be executed by an agent."""
    task_id: str = field(default_factory=_uuid)
    description: str = ""
    user_id: str = ""
    conversation_id: str | None = None
    platform: str | None = None
    channel_id: str | None = None
    context: dict[str, Any] = field(default_factory=dict)
    priority: int = 0
    parent_task_id: str | None = None


@dataclass
class AgentResult:
    """The result of an agent's task execution."""
    success: bool
    output: str
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    cost_usd: float = 0.0
    duration_ms: int = 0
    agent_id: str = ""
    agent_type: str = ""
    sub_results: list[AgentResult] = field(default_factory=list)


@dataclass
class AgentStreamEvent:
    """A single event during streaming agent execution."""
    agent_id: str
    event_type: str  # text_delta, tool_use, delegation, status_change, complete, error
    text: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentContext:
    """Runtime context passed to an agent — holds references to shared services."""
    # These are typed as Any to avoid circular imports; actual types are injected at runtime.
    shared_memory: Any = None  # SharedContext
    event_bus: Any = None  # EventBus
    skill_manager: Any = None  # SkillManager
    storage: Any = None  # StorageBackend
    parent_agent_id: str | None = None
    conversation_id: str | None = None
    user_id: str = ""
    platform: str | None = None
    channel_id: str | None = None


# ── Skill Types ─────────────────────────────────────────────────


@dataclass
class SkillContext:
    """Context passed to a skill during execution."""
    user_id: str = ""
    agent_id: str | None = None
    conversation_id: str | None = None
    working_directory: str | None = None
    platform: str | None = None
    channel_id: str | None = None
    config: dict[str, Any] = field(default_factory=dict)


@dataclass
class SkillResult:
    """The result of a skill execution."""
    success: bool
    output: str
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None


# ── Workflow Types ──────────────────────────────────────────────


@dataclass
class WorkflowStep:
    """A single step in a workflow pipeline."""
    step_id: str = field(default_factory=_uuid)
    name: str = ""
    step_type: str = ""  # WorkflowStepType value
    config: dict[str, Any] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)
    condition: str | None = None  # Expression to evaluate


@dataclass
class WorkflowDefinition:
    """A complete workflow pipeline definition."""
    workflow_id: str = field(default_factory=_uuid)
    name: str = ""
    description: str = ""
    trigger: dict[str, Any] = field(default_factory=dict)
    steps: list[WorkflowStep] = field(default_factory=list)
    variables: dict[str, Any] = field(default_factory=dict)


@dataclass
class WorkflowRunResult:
    """The result of a complete workflow run."""
    workflow_id: str = ""
    run_id: str = field(default_factory=_uuid)
    success: bool = True
    step_results: dict[str, Any] = field(default_factory=dict)
    duration_ms: int = 0
    error: str | None = None


# ── Notification Types ──────────────────────────────────────────


@dataclass
class Notification:
    """A notification to send to a user."""
    notification_id: str = field(default_factory=_uuid)
    title: str = ""
    message: str = ""
    severity: str = "info"  # NotificationSeverity value
    source: str = ""  # Which component generated it
    user_id: str | None = None  # None = broadcast
    platforms: list[str] = field(default_factory=list)  # Which platforms to send on
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=_utcnow)


# ── Knowledge Types ─────────────────────────────────────────────


@dataclass
class DocumentChunkResult:
    """A chunk of a document returned by the knowledge base retriever."""
    chunk_id: str = ""
    document_id: str = ""
    content: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    score: float = 0.0
    source: str = ""


# ── Replay/Debug Types ──────────────────────────────────────────


@dataclass
class TraceStep:
    """A single step in an execution trace."""
    step_id: str = field(default_factory=_uuid)
    timestamp: datetime = field(default_factory=_utcnow)
    component: str = ""  # agent, skill, provider, etc.
    action: str = ""  # what happened
    input_data: dict[str, Any] = field(default_factory=dict)
    output_data: dict[str, Any] = field(default_factory=dict)
    duration_ms: int = 0
    cost_usd: float = 0.0
    error: str | None = None
    children: list[TraceStep] = field(default_factory=list)


@dataclass
class ExecutionTrace:
    """A complete execution trace for replay/debug."""
    trace_id: str = field(default_factory=_uuid)
    task_id: str = ""
    user_id: str = ""
    started_at: datetime = field(default_factory=_utcnow)
    completed_at: datetime | None = None
    steps: list[TraceStep] = field(default_factory=list)
    total_cost_usd: float = 0.0
    total_duration_ms: int = 0
    success: bool = True
