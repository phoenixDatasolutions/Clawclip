"""ClawClip enumerations."""

from __future__ import annotations
from enum import Enum, Flag, auto


class Platform(str, Enum):
    """Supported messaging platforms."""
    TELEGRAM = "telegram"
    DISCORD = "discord"
    SLACK = "slack"
    WHATSAPP = "whatsapp"
    SIGNAL = "signal"
    MATRIX = "matrix"
    WEBUI = "webui"
    CLI = "cli"


class PlatformCapability(Flag):
    """Capabilities a platform may support."""
    TEXT = auto()
    FILES = auto()
    INLINE_BUTTONS = auto()
    REACTIONS = auto()
    THREADS = auto()
    STREAMING_EDITS = auto()
    RICH_FORMATTING = auto()
    VOICE = auto()
    IMAGES = auto()


class ModelCapability(Flag):
    """LLM model capabilities."""
    TEXT_GENERATION = auto()
    STREAMING = auto()
    TOOL_USE = auto()
    VISION = auto()
    CODE_EXECUTION = auto()
    LONG_CONTEXT = auto()
    JSON_MODE = auto()


class AgentStatus(str, Enum):
    """Agent lifecycle states."""
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Role(str, Enum):
    """User roles for RBAC."""
    ADMIN = "admin"
    USER = "user"
    READONLY = "readonly"
    OWNER = "owner"
    MEMBER = "member"
    VIEWER = "viewer"


class MessageRole(str, Enum):
    """Message roles in LLM conversations."""
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


class EventPriority(int, Enum):
    """Event handler priority (higher = runs first)."""
    CRITICAL = 100
    HIGH = 75
    NORMAL = 50
    LOW = 25
    BACKGROUND = 0


class TaskStatus(str, Enum):
    """Status for scheduled tasks and workflows."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PAUSED = "paused"


class WorkflowStepType(str, Enum):
    """Types of workflow pipeline steps."""
    LLM_CALL = "llm_call"
    SKILL_EXEC = "skill_exec"
    CONDITION = "condition"
    PARALLEL = "parallel"
    LOOP = "loop"
    HUMAN_APPROVAL = "human_approval"
    WEBHOOK = "webhook"
    NOTIFICATION = "notification"


class TriggerType(str, Enum):
    """Workflow trigger types."""
    MANUAL = "manual"
    CRON = "cron"
    WEBHOOK = "webhook"
    EVENT = "event"


class NotificationSeverity(str, Enum):
    """Notification alert severity levels."""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class SandboxStatus(str, Enum):
    """Docker sandbox container states."""
    CREATING = "creating"
    RUNNING = "running"
    STOPPED = "stopped"
    DESTROYED = "destroyed"
    ERROR = "error"
