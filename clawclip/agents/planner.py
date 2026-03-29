"""Task Planner — decomposes complex tasks into a validated DAG of subtasks."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from clawclip.core.types import AgentResult, TaskRequest

logger = logging.getLogger(__name__)


# ── SubTask dataclass ────────────────────────────────────────────


@dataclass
class SubTask:
    """A single node in the task execution DAG.

    Attributes:
        id: Unique identifier for this subtask.
        description: Human-readable description of what must be done.
        agent_type: Which built-in agent type should handle this (e.g. "code").
        depends_on: List of subtask IDs that must complete before this one.
        priority: Scheduling priority; higher values run first when possible.
    """

    id: str = field(default_factory=lambda: str(uuid4()))
    description: str = ""
    agent_type: str = "code"
    depends_on: list[str] = field(default_factory=list)
    priority: int = 0


# ── Planner LLM prompt ───────────────────────────────────────────

_PLANNER_SYSTEM_PROMPT = """You are a task planning assistant for ClawClip, a multi-agent AI platform.

Given a user task and a list of available agent types, decompose the task into an ordered list of
subtasks that can be executed by the agents.  Return ONLY valid JSON — no prose, no markdown fences.

Output format:
{
    "subtasks": [
        {
            "id": "t1",
            "description": "Clear description of what to do",
            "agent_type": "code",
            "depends_on": [],
            "priority": 0
        },
        {
            "id": "t2",
            "description": "Another step",
            "agent_type": "research",
            "depends_on": ["t1"],
            "priority": 0
        }
    ]
}

Rules:
- Use only the agent types provided in the available_agents list.
- Assign `depends_on` only to IDs that appear earlier in the subtasks list.
- The resulting dependency graph MUST be acyclic (DAG).
- Keep descriptions concise but complete — each subtask should be self-contained.
- Use short IDs like "t1", "t2", etc.
"""


# ── Cycle detection helper ───────────────────────────────────────


def _has_cycle(subtasks: list[SubTask]) -> bool:
    """Return True if *subtasks* contain a dependency cycle (DFS)."""
    graph: dict[str, list[str]] = {s.id: s.depends_on for s in subtasks}
    visited: set[str] = set()
    in_stack: set[str] = set()

    def _dfs(node: str) -> bool:
        if node in in_stack:
            return True
        if node in visited:
            return False
        visited.add(node)
        in_stack.add(node)
        for neighbour in graph.get(node, []):
            if _dfs(neighbour):
                return True
        in_stack.discard(node)
        return False

    return any(_dfs(s.id) for s in subtasks)


def _topological_sort(subtasks: list[SubTask]) -> list[SubTask]:
    """Return *subtasks* in topological order (Kahn's algorithm)."""
    id_map: dict[str, SubTask] = {s.id: s for s in subtasks}
    in_degree: dict[str, int] = {s.id: 0 for s in subtasks}
    dependents: dict[str, list[str]] = {s.id: [] for s in subtasks}

    for s in subtasks:
        for dep in s.depends_on:
            in_degree[s.id] += 1
            dependents[dep].append(s.id)

    # Seed with nodes that have no dependencies; break ties by priority (desc)
    queue: list[SubTask] = sorted(
        [s for s in subtasks if in_degree[s.id] == 0],
        key=lambda x: -x.priority,
    )
    result: list[SubTask] = []

    while queue:
        node = queue.pop(0)
        result.append(node)
        newly_free: list[SubTask] = []
        for child_id in dependents[node.id]:
            in_degree[child_id] -= 1
            if in_degree[child_id] == 0:
                newly_free.append(id_map[child_id])
        # Insert newly-freed nodes sorted by descending priority
        newly_free.sort(key=lambda x: -x.priority)
        queue = newly_free + queue  # prepend so higher-priority runs sooner

    return result


# ── TaskPlanner class ────────────────────────────────────────────


class TaskPlanner:
    """Decomposes complex tasks into a dependency-validated DAG of SubTasks.

    Usage::

        planner = TaskPlanner(provider=my_provider, model="claude-opus-4-6")
        plan = await planner.plan("build and deploy a REST API", ["code", "devops"])
        results = await planner.execute_plan(plan, engine)
    """

    def __init__(
        self,
        provider: Any,
        model: str = "claude-opus-4-6",
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> None:
        self._provider = provider
        self._model = model
        self._temperature = temperature
        self._max_tokens = max_tokens

    # ── Planning ─────────────────────────────────────────────────

    async def plan(
        self,
        task: str,
        available_agents: list[str],
    ) -> list[SubTask]:
        """Use an LLM to decompose *task* into a validated list of SubTasks.

        Args:
            task: Natural-language description of the overall goal.
            available_agents: Agent type names that may be assigned subtasks.

        Returns:
            List of :class:`SubTask` in dependency order, ready for execution.

        Raises:
            ValueError: If the LLM response cannot be parsed or contains a cycle.
        """
        user_prompt = (
            f"Available agent types: {available_agents}\n\nTask to decompose:\n{task}"
        )

        from clawclip.core.types import LLMMessage

        messages = [LLMMessage(role="user", content=user_prompt)]

        response = await self._provider.generate(
            messages=messages,
            model=self._model,
            temperature=self._temperature,
            max_tokens=self._max_tokens,
            system_prompt=_PLANNER_SYSTEM_PROMPT,
        )

        subtasks = self._parse_plan(response.content, available_agents)
        self._validate_dag(subtasks)
        return _topological_sort(subtasks)

    def _parse_plan(
        self,
        raw: str,
        available_agents: list[str],
    ) -> list[SubTask]:
        """Parse LLM JSON output into SubTask objects."""
        # Strip optional markdown fences
        text = raw.strip()
        if text.startswith("```"):
            start = text.find("{")
            end = text.rfind("}") + 1
            text = text[start:end] if start != -1 else text

        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Planner LLM returned invalid JSON: {exc}\n\nRaw:\n{raw}") from exc

        raw_subtasks = data.get("subtasks", [])
        if not isinstance(raw_subtasks, list):
            raise ValueError("Planner response missing 'subtasks' list.")

        subtasks: list[SubTask] = []
        for item in raw_subtasks:
            agent_type = item.get("agent_type", "code")
            # Coerce to a valid agent type
            if agent_type not in available_agents and available_agents:
                agent_type = available_agents[0]

            subtasks.append(
                SubTask(
                    id=str(item.get("id", str(uuid4()))),
                    description=str(item.get("description", "")),
                    agent_type=agent_type,
                    depends_on=[str(d) for d in item.get("depends_on", [])],
                    priority=int(item.get("priority", 0)),
                )
            )

        return subtasks

    def _validate_dag(self, subtasks: list[SubTask]) -> None:
        """Raise ValueError if the dependency graph is invalid."""
        ids = {s.id for s in subtasks}

        for s in subtasks:
            unknown = [dep for dep in s.depends_on if dep not in ids]
            if unknown:
                raise ValueError(
                    f"SubTask '{s.id}' references unknown dependencies: {unknown}"
                )

        if _has_cycle(subtasks):
            raise ValueError("Planner returned a dependency graph containing a cycle.")

    # ── Execution ────────────────────────────────────────────────

    async def execute_plan(
        self,
        plan: list[SubTask],
        engine: Any,  # AgentEngine — typed as Any to avoid circular imports
    ) -> dict[str, AgentResult]:
        """Execute the plan in topological order, running independent tasks in parallel.

        Args:
            plan: List of :class:`SubTask` objects (should already be sorted).
            engine: An :class:`~clawclip.agents.engine.AgentEngine` instance.

        Returns:
            Mapping of ``subtask.id -> AgentResult``.
        """
        results: dict[str, AgentResult] = {}
        completed: set[str] = set()
        remaining = list(plan)  # already topologically sorted

        while remaining:
            # Find all tasks whose dependencies are satisfied
            ready: list[SubTask] = [
                s for s in remaining
                if all(dep in completed for dep in s.depends_on)
            ]

            if not ready:
                # Should never happen if the DAG was validated, but guard against it.
                pending_ids = [s.id for s in remaining]
                logger.error(
                    "Planner deadlock: remaining tasks %s but none are ready", pending_ids
                )
                # Mark remaining as failed
                for s in remaining:
                    results[s.id] = AgentResult(
                        success=False,
                        output="Deadlock: dependency never satisfied",
                        agent_type=s.agent_type,
                    )
                break

            # Execute the ready batch in parallel
            logger.info(
                "Planner: executing batch of %d subtask(s): %s",
                len(ready),
                [s.id for s in ready],
            )

            batch_results = await asyncio.gather(
                *[self._run_subtask(s, engine) for s in ready],
                return_exceptions=True,
            )

            for subtask, result in zip(ready, batch_results):
                if isinstance(result, BaseException):
                    agent_result = AgentResult(
                        success=False,
                        output=str(result),
                        agent_type=subtask.agent_type,
                    )
                else:
                    agent_result = result  # type: ignore[assignment]

                results[subtask.id] = agent_result
                completed.add(subtask.id)
                remaining.remove(subtask)

        return results

    async def _run_subtask(self, subtask: SubTask, engine: Any) -> AgentResult:
        """Run a single subtask through the engine."""
        task = TaskRequest(
            description=subtask.description,
            priority=subtask.priority,
        )
        return await engine.execute_task(task, agent_type=subtask.agent_type)
