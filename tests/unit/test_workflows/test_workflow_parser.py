"""Unit tests for nexusai.workflows.parser — YAML workflow parsing and validation."""

from __future__ import annotations

import pytest

from nexusai.workflows.parser import parse_workflow, parse_workflow_file, validate_workflow
from nexusai.core.types import WorkflowDefinition


VALID_WORKFLOW_YAML = """
id: test_workflow
name: Test Workflow
description: A test workflow
trigger:
  type: manual
  config: {}
steps:
  - id: step1
    type: llm_call
    name: First step
    config:
      model: fake-model
      prompt: "Hello"
  - id: step2
    type: skill
    name: Second step
    depends_on: [step1]
    config:
      skill: shell
      tool: execute_bash
      arguments:
        command: "echo done"
"""

WORKFLOW_WITHOUT_ID = """
name: No ID Workflow
steps: []
"""

UNKNOWN_DEP_YAML = """
id: wf_deps
name: Bad deps
steps:
  - id: step1
    type: llm_call
    name: Orphan
    depends_on: [ghost]
    config: {}
"""

CYCLE_YAML = """
id: wf_cycle
name: Cycle Workflow
steps:
  - id: s1
    type: llm_call
    name: S1
    depends_on: [s2]
    config: {}
  - id: s2
    type: llm_call
    name: S2
    depends_on: [s1]
    config: {}
"""


@pytest.mark.unit
class TestWorkflowParser:

    def test_parse_valid_workflow(self) -> None:
        """parse_workflow returns a WorkflowDefinition with 2 steps."""
        wf = parse_workflow(VALID_WORKFLOW_YAML)
        assert isinstance(wf, WorkflowDefinition)
        assert wf.workflow_id == "test_workflow"
        assert len(wf.steps) == 2

    def test_validate_valid(self) -> None:
        """validate_workflow returns an empty list for a well-formed workflow."""
        wf = parse_workflow(VALID_WORKFLOW_YAML)
        errors = validate_workflow(wf)
        assert errors == []

    def test_validate_missing_id(self) -> None:
        """A workflow without an id field produces a validation error."""
        wf = parse_workflow(WORKFLOW_WITHOUT_ID)
        errors = validate_workflow(wf)
        assert any("workflow_id" in e for e in errors)

    def test_validate_unknown_dependency(self) -> None:
        """A step that depends_on a non-existent step produces a validation error."""
        wf = parse_workflow(UNKNOWN_DEP_YAML)
        errors = validate_workflow(wf)
        assert any("ghost" in e for e in errors)

    def test_validate_cycle_detected(self) -> None:
        """s1 <-> s2 mutual dependency produces a cycle validation error."""
        wf = parse_workflow(CYCLE_YAML)
        errors = validate_workflow(wf)
        assert any("ycle" in e for e in errors)  # "Cycle" case-insensitive

    def test_parse_file(self, tmp_path) -> None:
        """parse_workflow_file() loads YAML from disk correctly."""
        yaml_file = tmp_path / "test.yaml"
        yaml_file.write_text(VALID_WORKFLOW_YAML)

        wf = parse_workflow_file(str(yaml_file))
        assert wf.workflow_id == "test_workflow"
        assert len(wf.steps) == 2
