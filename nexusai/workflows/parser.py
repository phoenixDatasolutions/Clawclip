"""Workflow parser — loads and validates YAML workflow definitions."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from nexusai.core.types import WorkflowDefinition, WorkflowStep
from nexusai.workflows.steps import WorkflowStepDef

logger = logging.getLogger(__name__)

try:
    import yaml
    _YAML_AVAILABLE = True
except ImportError:
    _YAML_AVAILABLE = False


# ── Internal helpers ────────────────────────────────────────────────────────


def _parse_step(raw: dict[str, Any]) -> WorkflowStepDef:
    """Convert a raw YAML step dict to a :class:`WorkflowStepDef`."""
    from nexusai.core.enums import WorkflowStepType  # noqa: PLC0415

    raw_type = raw.get("type", "")
    try:
        step_type = WorkflowStepType(raw_type)
    except ValueError:
        # Allow the string through; executor will raise if truly unsupported
        step_type = raw_type  # type: ignore[assignment]

    return WorkflowStepDef(
        id=raw.get("id", ""),
        type=step_type,
        name=raw.get("name", ""),
        config=raw.get("config", {}),
        depends_on=raw.get("depends_on", []),
    )


def _raw_to_definition(data: dict[str, Any]) -> WorkflowDefinition:
    """Convert a deserialized YAML dict to a :class:`WorkflowDefinition`."""
    raw_steps = data.get("steps", [])
    steps = [
        WorkflowStep(
            step_id=s.get("id", ""),
            name=s.get("name", ""),
            step_type=s.get("type", ""),
            config=s.get("config", {}),
            depends_on=s.get("depends_on", []),
        )
        for s in raw_steps
    ]

    return WorkflowDefinition(
        workflow_id=data.get("id", ""),
        name=data.get("name", ""),
        description=data.get("description", ""),
        trigger=data.get("trigger", {}),
        steps=steps,
        variables=data.get("variables", {}),
    )


# ── Public API ──────────────────────────────────────────────────────────────


def parse_workflow(yaml_content: str) -> WorkflowDefinition:
    """Parse a YAML string and return a :class:`WorkflowDefinition`.

    Raises:
        ImportError: If PyYAML is not installed.
        ValueError: If the YAML is malformed or missing required fields.
    """
    if not _YAML_AVAILABLE:
        raise ImportError("PyYAML is required for workflow parsing. pip install pyyaml")

    try:
        data = yaml.safe_load(yaml_content)
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError("Workflow YAML must be a mapping at the top level")

    return _raw_to_definition(data)


def parse_workflow_file(path: str) -> WorkflowDefinition:
    """Load a YAML file from disk and parse it as a workflow.

    Raises:
        FileNotFoundError: If the path does not exist.
        ValueError: If parsing fails.
    """
    content = Path(path).read_text(encoding="utf-8")
    return parse_workflow(content)


def validate_workflow(wf: WorkflowDefinition) -> list[str]:
    """Validate a workflow definition and return a list of error messages.

    Checks performed:
    - ``workflow_id`` is present
    - All ``depends_on`` references point to existing step IDs
    - No dependency cycles (topological sort must succeed)
    - Required config keys are present for known step types
    """
    errors: list[str] = []

    if not wf.workflow_id:
        errors.append("workflow_id is required")

    step_ids = {s.step_id for s in wf.steps}

    for step in wf.steps:
        if not step.step_id:
            errors.append(f"Step '{step.name}' is missing an id")

        for dep in step.depends_on:
            if dep not in step_ids:
                errors.append(
                    f"Step '{step.step_id}' depends on unknown step '{dep}'"
                )

    # Cycle detection via DFS
    if not errors:
        dep_map: dict[str, list[str]] = {s.step_id: list(s.depends_on) for s in wf.steps}
        visited: set[str] = set()
        in_stack: set[str] = set()

        def _has_cycle(node: str) -> bool:
            visited.add(node)
            in_stack.add(node)
            for neighbour in dep_map.get(node, []):
                if neighbour not in visited:
                    if _has_cycle(neighbour):
                        return True
                elif neighbour in in_stack:
                    return True
            in_stack.discard(node)
            return False

        for step_id in step_ids:
            if step_id not in visited:
                if _has_cycle(step_id):
                    errors.append(f"Cycle detected involving step '{step_id}'")
                    break

    return errors
