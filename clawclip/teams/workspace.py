"""WorkspaceManager — in-memory workspace storage for team collaboration."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TypedDict
from uuid import uuid4

logger = logging.getLogger(__name__)


class Workspace(TypedDict):
    """A collaborative workspace shared by a group of users."""
    id: str
    name: str
    owner_id: str
    members: dict[str, str]   # user_id → role
    created_at: str            # ISO-8601 UTC


class WorkspaceManager:
    """Manages in-memory workspaces.

    Note: this is intentionally in-memory for lightweight use.  Persistence
    can be added later by swapping the backing store.
    """

    def __init__(self) -> None:
        self._workspaces: dict[str, Workspace] = {}

    async def create_workspace(self, name: str, owner_id: str) -> Workspace:
        """Create a new workspace owned by `owner_id` and return it."""
        workspace_id = str(uuid4())
        workspace: Workspace = {
            "id": workspace_id,
            "name": name,
            "owner_id": owner_id,
            "members": {owner_id: "owner"},
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self._workspaces[workspace_id] = workspace
        logger.info("Created workspace %s (%r) owner=%s", workspace_id, name, owner_id)
        return workspace

    async def invite_member(
        self,
        workspace_id: str,
        user_id: str,
        role: str = "member",
    ) -> None:
        """Add `user_id` to the workspace with the given role."""
        workspace = self._workspaces.get(workspace_id)
        if workspace is None:
            raise ValueError(f"Workspace {workspace_id!r} not found")
        workspace["members"][user_id] = role
        logger.debug("Invited %s to workspace %s as %r", user_id, workspace_id, role)

    async def remove_member(self, workspace_id: str, user_id: str) -> None:
        """Remove `user_id` from the workspace.

        The owner cannot be removed.
        """
        workspace = self._workspaces.get(workspace_id)
        if workspace is None:
            raise ValueError(f"Workspace {workspace_id!r} not found")
        if user_id == workspace["owner_id"]:
            raise ValueError("Cannot remove the workspace owner")
        workspace["members"].pop(user_id, None)
        logger.debug("Removed %s from workspace %s", user_id, workspace_id)

    async def get_workspace(self, workspace_id: str) -> Workspace | None:
        """Return the workspace dict, or None if not found."""
        return self._workspaces.get(workspace_id)

    async def list_user_workspaces(self, user_id: str) -> list[Workspace]:
        """Return all workspaces that `user_id` is a member of."""
        return [
            ws for ws in self._workspaces.values()
            if user_id in ws["members"]
        ]
