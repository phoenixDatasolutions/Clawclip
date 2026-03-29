"""TeamSharingManager — share conversations and knowledge bases across workspaces."""

from __future__ import annotations

import logging
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexusai.storage.models.conversation import Conversation

logger = logging.getLogger(__name__)


class TeamSharingManager:
    """Tracks which conversations and knowledge bases are shared in a workspace.

    Workspace → conversation and knowledge-base mappings are held in memory.
    Conversation metadata is fetched from the DB when listing shared items.
    """

    def __init__(self) -> None:
        # workspace_id → set of conversation IDs
        self._shared_convs: dict[str, set[str]] = defaultdict(set)
        # workspace_id → set of knowledge base IDs
        self._shared_kbs: dict[str, set[str]] = defaultdict(set)

    async def share_conversation(self, conv_id: str, workspace_id: str) -> None:
        """Make a conversation visible to all workspace members."""
        self._shared_convs[workspace_id].add(conv_id)
        logger.debug("Shared conversation %s in workspace %s", conv_id, workspace_id)

    async def unshare_conversation(self, conv_id: str, workspace_id: str) -> None:
        """Remove a conversation from the workspace shared set."""
        self._shared_convs[workspace_id].discard(conv_id)
        logger.debug("Unshared conversation %s from workspace %s", conv_id, workspace_id)

    async def get_shared_conversations(
        self,
        workspace_id: str,
        session: AsyncSession,
    ) -> list[dict]:
        """Return metadata dicts for conversations shared in `workspace_id`.

        Fetches each conversation from the DB; conversations that no longer
        exist are silently excluded.
        """
        conv_ids = list(self._shared_convs.get(workspace_id, set()))
        if not conv_ids:
            return []

        stmt = select(Conversation).where(Conversation.id.in_(conv_ids))
        result = await session.execute(stmt)
        rows = result.scalars().all()

        return [
            {
                "id": c.id,
                "title": getattr(c, "title", None),
                "user_id": c.user_id,
                "platform": getattr(c, "platform", None),
                "created_at": c.created_at.isoformat() if hasattr(c, "created_at") else None,
            }
            for c in rows
        ]

    async def share_knowledge_base(self, kb_id: str, workspace_id: str) -> None:
        """Make a knowledge base accessible to all workspace members."""
        self._shared_kbs[workspace_id].add(kb_id)
        logger.debug("Shared knowledge base %s in workspace %s", kb_id, workspace_id)

    async def unshare_knowledge_base(self, kb_id: str, workspace_id: str) -> None:
        """Remove a knowledge base from the workspace shared set."""
        self._shared_kbs[workspace_id].discard(kb_id)
        logger.debug("Unshared knowledge base %s from workspace %s", kb_id, workspace_id)

    def get_shared_knowledge_bases(self, workspace_id: str) -> list[str]:
        """Return IDs of knowledge bases shared in `workspace_id`."""
        return list(self._shared_kbs.get(workspace_id, set()))
