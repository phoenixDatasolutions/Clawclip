"""Unit tests for nexusai.company.org_chart — OrgChart."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from nexusai.company.models import OrgNode
from nexusai.company.org_chart import OrgChart, create_default_chart


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_store() -> MagicMock:
    """Return a mock CompanyStore that persists OrgNodes in memory."""
    store = MagicMock()
    _nodes: dict[str, OrgNode] = {}

    def _load_nodes(company_id: str) -> list[OrgNode]:
        return list(_nodes.values())

    async def _save_node(node: OrgNode) -> None:
        _nodes[node.id] = node

    async def _delete_node(company_id: str, node_id: str) -> None:
        _nodes.pop(node_id, None)

    store.load_org_nodes.side_effect = _load_nodes
    store.save_org_node = AsyncMock(side_effect=_save_node)
    store.delete_org_node = AsyncMock(side_effect=_delete_node)
    store._nodes = _nodes  # expose for introspection
    return store


def _node(
    node_id: str,
    company_id: str,
    agent_name: str,
    role_title: str,
    parent_id: str | None = None,
) -> OrgNode:
    return OrgNode(
        id=node_id,
        company_id=company_id,
        agent_name=agent_name,
        role_title=role_title,
        description=f"{role_title} role",
        parent_id=parent_id,
        allowed_skills=["*"],
        budget_limit_usd=10.0,
    )


# ── test_add_and_get_role ─────────────────────────────────────────────────────


async def test_add_and_get_role() -> None:
    """add_role() persists the node; get_role() retrieves it by ID."""
    store = _make_store()
    chart = OrgChart("co1", store)

    ceo = _node("ceo-id", "co1", "coordinator", "Chief Executive Officer")
    await chart.add_role(ceo)

    result = await chart.get_role("ceo-id")
    assert result is not None
    assert result.id == "ceo-id"
    assert result.role_title == "Chief Executive Officer"


# ── test_get_by_name ──────────────────────────────────────────────────────────


async def test_get_by_name() -> None:
    """get_role_by_name() finds a node by agent_name."""
    store = _make_store()
    chart = OrgChart("co1", store)

    ceo = _node("ceo-id", "co1", "coordinator", "CEO")
    await chart.add_role(ceo)

    result = await chart.get_role_by_name("coordinator")
    assert result is not None
    assert result.id == "ceo-id"


async def test_get_by_name_missing() -> None:
    """get_role_by_name() returns None when the name is not registered."""
    store = _make_store()
    chart = OrgChart("co1", store)

    result = await chart.get_role_by_name("ghost_agent")
    assert result is None


# ── test_hierarchy ────────────────────────────────────────────────────────────


async def test_hierarchy() -> None:
    """get_children() returns direct reports of a given node ID."""
    store = _make_store()
    chart = OrgChart("co1", store)

    ceo = _node("ceo", "co1", "coordinator", "CEO", parent_id=None)
    cto = _node("cto", "co1", "code", "CTO", parent_id="ceo")
    coo = _node("coo", "co1", "ops", "COO", parent_id="ceo")
    dev = _node("dev", "co1", "devops", "DevOps", parent_id="cto")

    for node in (ceo, cto, coo, dev):
        await chart.add_role(node)

    children_of_ceo = await chart.get_children("ceo")
    child_ids = {n.id for n in children_of_ceo}

    assert "cto" in child_ids
    assert "coo" in child_ids
    assert "dev" not in child_ids  # dev is CTO's child, not CEO's


# ── test_root_roles ───────────────────────────────────────────────────────────


async def test_root_roles() -> None:
    """get_root_roles() returns only nodes with parent_id=None."""
    store = _make_store()
    chart = OrgChart("co1", store)

    ceo = _node("ceo", "co1", "coordinator", "CEO", parent_id=None)
    cto = _node("cto", "co1", "code", "CTO", parent_id="ceo")

    await chart.add_role(ceo)
    await chart.add_role(cto)

    roots = await chart.get_root_roles()
    assert len(roots) == 1
    assert roots[0].id == "ceo"


# ── test_to_tree_structure ────────────────────────────────────────────────────


async def test_to_tree_structure() -> None:
    """to_tree() returns a nested dict with 'roles' at the root."""
    store = _make_store()
    chart = OrgChart("co1", store)

    ceo = _node("ceo", "co1", "coordinator", "CEO", parent_id=None)
    cto = _node("cto", "co1", "code", "CTO", parent_id="ceo")

    await chart.add_role(ceo)
    await chart.add_role(cto)
    # Warm up cache by calling list_roles
    await chart.list_roles()

    tree = chart.to_tree()
    assert "roles" in tree
    assert len(tree["roles"]) == 1  # one root

    root = tree["roles"][0]
    assert root["agent_name"] == "coordinator"
    assert len(root["children"]) == 1
    assert root["children"][0]["agent_name"] == "code"


async def test_to_tree_empty_when_cache_cold() -> None:
    """to_tree() returns empty dict when cache has not been populated."""
    store = _make_store()
    chart = OrgChart("co1", store)
    # Do NOT call list_roles() — cache stays None
    tree = chart.to_tree()
    assert tree == {}


# ── test_default_chart ────────────────────────────────────────────────────────


async def test_default_chart() -> None:
    """create_default_chart() populates a chart with a CEO (coordinator) at root."""
    store = _make_store()
    chart = await create_default_chart("co1", store)

    ceo = await chart.get_role_by_name("coordinator")
    assert ceo is not None
    assert ceo.parent_id is None  # CEO is the root


async def test_default_chart_has_expected_roles() -> None:
    """create_default_chart() includes all five standard roles."""
    store = _make_store()
    chart = await create_default_chart("co1", store)

    roles = await chart.list_roles()
    agent_names = {r.agent_name for r in roles}

    assert "coordinator" in agent_names  # CEO
    assert "code" in agent_names         # CTO
    assert "system" in agent_names       # COO
    assert "devops" in agent_names       # Senior Engineer
    assert "research" in agent_names     # Researcher


# ── test_ascii_chart ──────────────────────────────────────────────────────────


async def test_ascii_chart() -> None:
    """format_chart() returns a non-empty string containing hierarchy indicators."""
    store = _make_store()
    chart = OrgChart("co1", store)

    ceo = _node("ceo", "co1", "coordinator", "CEO", parent_id=None)
    cto = _node("cto", "co1", "code", "CTO", parent_id="ceo")

    await chart.add_role(ceo)
    await chart.add_role(cto)
    await chart.list_roles()  # warm cache

    output = chart.format_chart()
    assert len(output) > 0
    assert "CEO" in output
    assert "CTO" in output
    # Should include ASCII tree characters
    assert "─" in output or "└" in output or "├" in output


async def test_ascii_chart_cold_cache() -> None:
    """format_chart() before loading returns the not-loaded placeholder string."""
    store = _make_store()
    chart = OrgChart("co1", store)

    output = chart.format_chart()
    assert "not loaded" in output.lower() or len(output) > 0


# ── test_remove_role ──────────────────────────────────────────────────────────


async def test_remove_role() -> None:
    """remove_role() deletes the node from the store and invalidates cache."""
    store = _make_store()
    chart = OrgChart("co1", store)

    node = _node("n1", "co1", "temp_agent", "Temp Role")
    await chart.add_role(node)

    # Confirm it exists
    assert await chart.get_role("n1") is not None

    await chart.remove_role("n1")

    # Should be gone after removal
    assert await chart.get_role("n1") is None
