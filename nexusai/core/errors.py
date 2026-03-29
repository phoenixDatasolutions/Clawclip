"""NexusAI exception hierarchy."""

from __future__ import annotations


class NexusError(Exception):
    """Base exception for all NexusAI errors."""

    def __init__(self, message: str = "", *, details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


# --- Platform Errors ---

class PlatformError(NexusError):
    """Error related to a messaging platform adapter."""

class PlatformConnectionError(PlatformError):
    """Failed to connect to a messaging platform."""

class PlatformSendError(PlatformError):
    """Failed to send a message on a platform."""

class PlatformNotSupportedError(PlatformError):
    """Requested capability not supported by this platform."""


# --- Provider Errors ---

class ProviderError(NexusError):
    """Error related to an LLM provider."""

class ProviderConnectionError(ProviderError):
    """Failed to connect to an LLM provider."""

class ProviderRateLimitError(ProviderError):
    """LLM provider rate limit exceeded."""

    def __init__(self, message: str = "", *, retry_after: float | None = None, **kwargs) -> None:
        super().__init__(message, **kwargs)
        self.retry_after = retry_after

class ProviderAuthError(ProviderError):
    """Invalid or missing API key for LLM provider."""

class ModelNotFoundError(ProviderError):
    """Requested model not found in provider."""


# --- Agent Errors ---

class AgentError(NexusError):
    """Error related to agent execution."""

class AgentTimeoutError(AgentError):
    """Agent execution timed out."""

class AgentDelegationError(AgentError):
    """Failed to delegate task to another agent."""

class MaxDelegationsError(AgentError):
    """Maximum delegation depth exceeded."""


# --- Skill Errors ---

class SkillError(NexusError):
    """Error related to skill execution."""

class SkillNotFoundError(SkillError):
    """Requested skill not registered."""

class SkillPermissionError(SkillError):
    """Agent/user lacks permission to use this skill."""

class SkillExecutionError(SkillError):
    """Skill execution failed."""


# --- Auth/Security Errors ---

class AuthError(NexusError):
    """Authentication or authorization error."""

class UnauthorizedError(AuthError):
    """User not authenticated."""

class ForbiddenError(AuthError):
    """User authenticated but lacks permission."""

class RateLimitError(AuthError):
    """User rate limit exceeded."""

    def __init__(self, message: str = "", *, limit_type: str = "", **kwargs) -> None:
        super().__init__(message, **kwargs)
        self.limit_type = limit_type


# --- Config Errors ---

class ConfigError(NexusError):
    """Configuration error."""

class ConfigValidationError(ConfigError):
    """Configuration value validation failed."""

class ConfigNotFoundError(ConfigError):
    """Configuration file not found."""


# --- Storage Errors ---

class StorageError(NexusError):
    """Database or storage error."""

class RecordNotFoundError(StorageError):
    """Requested record not found."""


# --- Workflow Errors ---

class WorkflowError(NexusError):
    """Workflow execution error."""

class WorkflowValidationError(WorkflowError):
    """Workflow definition is invalid."""

class WorkflowStepError(WorkflowError):
    """A workflow step failed."""


# --- Sandbox Errors ---

class SandboxError(NexusError):
    """Docker sandbox error."""

class SandboxUnavailableError(SandboxError):
    """Docker not available for sandboxing."""
