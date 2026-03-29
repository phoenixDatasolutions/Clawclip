"""Unit tests for nexusai.agents.planner — TaskPlanner DAG decomposition."""

from __future__ import annotations

import pytest

from tests.conftest import FakeLLMProvider
from nexusai.agents.planner import SubTask, TaskPlanner, _has_cycle, _topological_sort


FAKE_PLAN_RESPONSE = """
{
  "subtasks": [
    {"id": "t1", "description": "First task", "agent_type": "code", "depends_on": [], "priority": 1},
    {"id": "t2", "description": "Second task", "agent_type": "research", "depends_on": ["t1"], "priority": 0}
  ]
}
"""

FAKE_PLAN_WITH_PARALLEL = """
{
  "subtasks": [
    {"id": "t1", "description": "Task 1", "agent_type": "code", "depends_on": [], "priority": 0},
    {"id": "t2", "description": "Task 2", "agent_type": "code", "depends_on": [], "priority": 0},
    {"id": "t3", "description": "Task 3", "agent_type": "code", "depends_on": ["t1", "t2"], "priority": 0}
  ]
}
"""


@pytest.mark.unit
class TestTaskPlanner:

    async def test_plan_returns_subtasks(self) -> None:
        """plan() returns a list of SubTask objects parsed from LLM output."""
        provider = FakeLLMProvider([FAKE_PLAN_RESPONSE])
        planner = TaskPlanner(provider=provider)

        subtasks = await planner.plan("complex task", ["code", "research"])

        assert len(subtasks) == 2
        assert all(isinstance(s, SubTask) for s in subtasks)

    async def test_dag_validation_no_cycles(self) -> None:
        """A valid plan with no cycles passes _validate_dag without raising."""
        planner = TaskPlanner(provider=FakeLLMProvider())
        subtasks = [
            SubTask(id="t1", description="A", depends_on=[]),
            SubTask(id="t2", description="B", depends_on=["t1"]),
        ]
        # Should not raise
        planner._validate_dag(subtasks)

    async def test_dag_validation_detects_cycle(self) -> None:
        """A plan with t1 -> t2 -> t1 raises ValueError."""
        planner = TaskPlanner(provider=FakeLLMProvider())
        subtasks = [
            SubTask(id="t1", description="A", depends_on=["t2"]),
            SubTask(id="t2", description="B", depends_on=["t1"]),
        ]
        with pytest.raises(ValueError, match="cycle"):
            planner._validate_dag(subtasks)

    async def test_unknown_dependency_raises(self) -> None:
        """depends_on=['nonexistent'] raises ValueError."""
        planner = TaskPlanner(provider=FakeLLMProvider())
        subtasks = [
            SubTask(id="t1", description="A", depends_on=["nonexistent"]),
        ]
        with pytest.raises(ValueError, match="unknown dependencies"):
            planner._validate_dag(subtasks)

    async def test_topological_order(self) -> None:
        """t2 depends on t1 → t1 appears before t2 in topological sort."""
        subtasks = [
            SubTask(id="t1", description="A", depends_on=[]),
            SubTask(id="t2", description="B", depends_on=["t1"]),
        ]
        ordered = _topological_sort(subtasks)
        ids = [s.id for s in ordered]
        assert ids.index("t1") < ids.index("t2")

    async def test_parallel_detection(self) -> None:
        """t1 and t2 are independent; both appear before t3 in sorted order."""
        provider = FakeLLMProvider([FAKE_PLAN_WITH_PARALLEL])
        planner = TaskPlanner(provider=provider)

        subtasks = await planner.plan("parallel task", ["code"])

        ids = [s.id for s in subtasks]
        t3_index = ids.index("t3")
        t1_index = ids.index("t1")
        t2_index = ids.index("t2")
        assert t1_index < t3_index
        assert t2_index < t3_index
