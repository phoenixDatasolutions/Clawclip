"""ClawClip Protocol definitions — interfaces that adapters/providers/agents implement."""

from clawclip.core.interfaces.agent import Agent
from clawclip.core.interfaces.formatter import OutputFormatter
from clawclip.core.interfaces.llm import LLMProvider
from clawclip.core.interfaces.platform import PlatformAdapter
from clawclip.core.interfaces.skill import Skill
from clawclip.core.interfaces.storage import StorageBackend

__all__ = [
    "Agent",
    "LLMProvider",
    "OutputFormatter",
    "PlatformAdapter",
    "Skill",
    "StorageBackend",
]
