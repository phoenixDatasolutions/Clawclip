"""Agent Sandbox — per-agent tool permission enforcement."""

from __future__ import annotations

import logging
from typing import Any

from nexusai.core.types import ToolDefinition

logger = logging.getLogger(__name__)

_WILDCARD = "*"


class AgentSandbox:
    """Enforces which skills and tools an agent is allowed to use.

    Permission model
    ----------------
    - If ``allowed_skills`` is empty → **all skills denied** (default-deny).
    - ``"*"`` in ``allowed_skills`` → all skills (and their tools) allowed.
    - Otherwise only the explicitly listed skill names are permitted.

    Tool-level control (optional)
    ------------------------------
    ``allowed_tools`` is a list of ``"skill_name:tool_name"`` strings, or
    ``"skill_name:*"`` to allow all tools within a skill.  When *not* provided,
    any tool belonging to an allowed skill is permitted.

    Example::

        sandbox = AgentSandbox(
            allowed_skills=["shell", "files"],
            allowed_tools=["shell:run_command", "files:*"],
        )
        sandbox.can_use_skill("shell")          # True
        sandbox.can_use_tool("shell", "run_command")  # True
        sandbox.can_use_tool("shell", "dangerous_op") # False (not in allowed_tools)
        sandbox.can_use_skill("git")            # False
    """

    def __init__(
        self,
        allowed_skills: list[str],
        allowed_tools: list[str] | None = None,
    ) -> None:
        self._allowed_skills: list[str] = list(allowed_skills)
        # Parse tool rules into a dict: skill_name -> set[tool_name] | {"*"}
        self._tool_rules: dict[str, set[str]] = {}
        if allowed_tools is not None:
            for entry in allowed_tools:
                if ":" in entry:
                    skill_part, tool_part = entry.split(":", 1)
                    self._tool_rules.setdefault(skill_part, set()).add(tool_part)
                else:
                    # Bare skill name without tool specifier — allow all tools
                    self._tool_rules.setdefault(entry, set()).add(_WILDCARD)

    # ── Skill-level checks ───────────────────────────────────────

    def can_use_skill(self, skill_name: str) -> bool:
        """Return True if this agent may use *skill_name*.

        ``"*"`` in the allowed list grants access to all skills.
        An empty allowed list denies everything.
        """
        if not self._allowed_skills:
            return False
        if _WILDCARD in self._allowed_skills:
            return True
        return skill_name in self._allowed_skills

    # ── Tool-level checks ────────────────────────────────────────

    def can_use_tool(self, skill_name: str, tool_name: str) -> bool:
        """Return True if this agent may call *tool_name* within *skill_name*.

        Evaluation order:
        1. If the skill itself is not allowed → deny.
        2. If no tool-level rules were supplied at construction → allow all
           tools within the skill.
        3. If tool rules exist for this skill → check them (``"*"`` means all).
        4. Otherwise deny.
        """
        if not self.can_use_skill(skill_name):
            return False

        if not self._tool_rules:
            # No fine-grained tool rules → any tool in an allowed skill is OK.
            return True

        allowed_for_skill = self._tool_rules.get(skill_name)
        if allowed_for_skill is None:
            # Skill is allowed but no specific tool rules → grant all tools.
            return True

        return _WILDCARD in allowed_for_skill or tool_name in allowed_for_skill

    # ── Bulk filtering ───────────────────────────────────────────

    def filter_tools(self, tools: list[ToolDefinition]) -> list[ToolDefinition]:
        """Return only the tools from *tools* that pass this sandbox's rules.

        The tool's ``name`` is expected to follow the convention
        ``"skill_name__tool_name"`` (double-underscore separator) or simply
        ``"tool_name"`` when the skill prefix is unknown.  When the separator
        is absent, the tool is checked only against :meth:`can_use_skill` using
        the full name as the skill.

        Additionally, each tool's ``required_permissions`` are checked — if the
        tool declares permissions, all of them must be in the allowed skills.
        """
        kept: list[ToolDefinition] = []
        for tool in tools:
            if self._tool_allowed(tool):
                kept.append(tool)
            else:
                logger.debug(
                    "AgentSandbox: blocked tool '%s' (not in allowed set)", tool.name
                )
        return kept

    def _tool_allowed(self, tool: ToolDefinition) -> bool:
        """Internal check for a single ToolDefinition."""
        # 1. Check required_permissions declared on the tool itself
        if tool.required_permissions:
            if not all(self.can_use_skill(perm) for perm in tool.required_permissions):
                return False

        # 2. Parse skill/tool from the tool name
        if "__" in tool.name:
            skill_name, tool_name = tool.name.split("__", 1)
        else:
            # Treat the whole name as the skill; tool name is the same
            skill_name = tool.name
            tool_name = tool.name

        return self.can_use_tool(skill_name, tool_name)

    # ── Repr ─────────────────────────────────────────────────────

    def __repr__(self) -> str:
        return (
            f"AgentSandbox(allowed_skills={self._allowed_skills!r}, "
            f"tool_rules={self._tool_rules!r})"
        )
