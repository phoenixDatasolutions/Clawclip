"""NexusAI Protocol definitions — interfaces that adapters/providers/agents implement."""

from nexusai.core.interfaces.agent import Agent
from nexusai.core.interfaces.formatter import OutputFormatter
from nexusai.core.interfaces.llm import LLMProvider
from nexusai.core.interfaces.platform import PlatformAdapter
from nexusai.core.interfaces.skill import Skill
from nexusai.core.interfaces.storage import StorageBackend

__all__ = [
    "Agent",
    "LLMProvider",
    "OutputFormatter",
    "PlatformAdapter",
    "Skill",
    "StorageBackend",
]
