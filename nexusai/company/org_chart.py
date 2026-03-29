"""OrgChart — hierarchical agent role management for a company."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from uuid import uuid4

from nexusai.company.models import OrgNode

if TYPE_CHECKING:
    from nexusai.company.store import CompanyStore

logger = logging.getLogger(__name__)


class OrgChart:
    """Manages the hierarchical structure of agent roles within a company.

    Roles are stored persistently via CompanyStore and cached in memory.
    """

    def __init__(self, company_id: str, store: "CompanyStore") -> None:
        self._company_id = company_id
        self._store = store
        self._cache: dict[str, OrgNode] | None = None

    # ── Cache helpers ────────────────────────────────────────────

    async def _get_all(self) -> dict[str, OrgNode]:
        if self._cache is None:
            nodes = self._store.load_org_nodes(self._company_id)
            self._cache = {n.id: n for n in nodes}
        return self._cache

    def _invalidate(self) -> None:
        self._cache = None

    # ── CRUD ─────────────────────────────────────────────────────

    async def add_role(self, node: OrgNode) -> None:
        """Add or update a role in the org chart."""
        await self._store.save_org_node(node)
        self._invalidate()
        logger.info("OrgChart[%s]: added role %s (%s)", self._company_id, node.role_title, node.id)

    async def remove_role(self, node_id: str) -> None:
        """Remove a role by ID."""
        await self._store.delete_org_node(self._company_id, node_id)
        self._invalidate()
        logger.info("OrgChart[%s]: removed role %s", self._company_id, node_id)

    async def get_role(self, node_id: str) -> OrgNode | None:
        nodes = await self._get_all()
        return nodes.get(node_id)

    async def get_role_by_name(self, agent_name: str) -> OrgNode | None:
        nodes = await self._get_all()
        for n in nodes.values():
            if n.agent_name == agent_name:
                return n
        return None

    async def list_roles(self) -> list[OrgNode]:
        nodes = await self._get_all()
        return list(nodes.values())

    async def get_children(self, parent_id: str) -> list[OrgNode]:
        nodes = await self._get_all()
        return [n for n in nodes.values() if n.parent_id == parent_id]

    async def get_root_roles(self) -> list[OrgNode]:
        """Return top-level roles (no parent)."""
        nodes = await self._get_all()
        return [n for n in nodes.values() if n.parent_id is None]

    # ── Tree representation ──────────────────────────────────────

    def to_tree(self) -> dict:
        """Return a nested dict representation of the org chart.

        Returns an empty dict if cache is not populated yet.
        Call list_roles() first to ensure cache is warm.
        """
        if self._cache is None:
            return {}
        nodes = self._cache

        def build(node_id: str) -> dict:
            node = nodes[node_id]
            children = [n for n in nodes.values() if n.parent_id == node_id]
            return {
                "id": node.id,
                "agent_name": node.agent_name,
                "role_title": node.role_title,
                "description": node.description,
                "allowed_skills": node.allowed_skills,
                "budget_limit_usd": node.budget_limit_usd,
                "children": [build(c.id) for c in children],
            }

        roots = [n for n in nodes.values() if n.parent_id is None]
        return {"roles": [build(r.id) for r in roots]}

    def format_chart(self) -> str:
        """Render the org chart as an ASCII tree.

        Example::

            CEO (agent: coordinator)
            ├── CTO (agent: code_agent)
            │   ├── Senior Engineer (agent: devops_agent)
            │   └── Researcher (agent: research_agent)
            └── COO (agent: system_agent)
        """
        if self._cache is None:
            return "(org chart not loaded — call list_roles() first)"

        nodes = self._cache
        lines: list[str] = []

        def render(node: OrgNode, prefix: str, is_last: bool) -> None:
            connector = "└── " if is_last else "├── "
            lines.append(f"{prefix}{connector}{node.role_title} (agent: {node.agent_name})")
            children = [n for n in nodes.values() if n.parent_id == node.id]
            child_prefix = prefix + ("    " if is_last else "│   ")
            for i, child in enumerate(children):
                render(child, child_prefix, i == len(children) - 1)

        roots = [n for n in nodes.values() if n.parent_id is None]
        for i, root in enumerate(roots):
            lines.append(f"{root.role_title} (agent: {root.agent_name})")
            children = [n for n in nodes.values() if n.parent_id == root.id]
            for j, child in enumerate(children):
                render(child, "", j == len(children) - 1)

        return "\n".join(lines)

    # ── Factory ──────────────────────────────────────────────────


async def create_default_chart(company_id: str, store: "CompanyStore") -> OrgChart:
    """Create a default org chart with the standard NexusAI hierarchy.

    Structure::

        CEO — CoordinatorAgent
        ├── CTO — CodeAgent
        │   ├── Senior Engineer — DevOpsAgent
        │   └── Researcher — ResearchAgent
        └── COO — SystemAgent
    """
    chart = OrgChart(company_id, store)

    ceo_id = str(uuid4())
    cto_id = str(uuid4())
    coo_id = str(uuid4())
    eng_id = str(uuid4())
    res_id = str(uuid4())

    roles = [
        OrgNode(
            id=ceo_id,
            company_id=company_id,
            agent_name="coordinator",
            role_title="Chief Executive Officer",
            description=(
                "Sets overall direction, decomposes company goals into tasks, "
                "delegates to department heads, and monitors progress."
            ),
            parent_id=None,
            allowed_skills=["*"],
            budget_limit_usd=50.0,
        ),
        OrgNode(
            id=cto_id,
            company_id=company_id,
            agent_name="code",
            role_title="Chief Technology Officer",
            description=(
                "Leads technical execution, writes and reviews code, "
                "oversees engineering and research functions."
            ),
            parent_id=ceo_id,
            allowed_skills=["code_execution", "file_ops", "git"],
            budget_limit_usd=20.0,
        ),
        OrgNode(
            id=coo_id,
            company_id=company_id,
            agent_name="system",
            role_title="Chief Operating Officer",
            description=(
                "Manages infrastructure, deployments, monitoring, and operational "
                "processes to keep the company running smoothly."
            ),
            parent_id=ceo_id,
            allowed_skills=["shell", "docker", "monitoring"],
            budget_limit_usd=15.0,
        ),
        OrgNode(
            id=eng_id,
            company_id=company_id,
            agent_name="devops",
            role_title="Senior Engineer",
            description=(
                "Handles DevOps tasks: CI/CD pipelines, containerisation, "
                "infrastructure-as-code, and deployment automation."
            ),
            parent_id=cto_id,
            allowed_skills=["shell", "docker", "file_ops"],
            budget_limit_usd=10.0,
        ),
        OrgNode(
            id=res_id,
            company_id=company_id,
            agent_name="research",
            role_title="Researcher",
            description=(
                "Conducts web research, synthesises information, and provides "
                "evidence-based recommendations to the CTO."
            ),
            parent_id=cto_id,
            allowed_skills=["web_search", "web_fetch", "file_ops"],
            budget_limit_usd=10.0,
        ),
    ]

    for role in roles:
        await chart.add_role(role)

    logger.info("Created default org chart for company %s", company_id)
    return chart
