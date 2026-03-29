"""BranchManager — high-level operations for conversation branching."""

from __future__ import annotations

import logging
from typing import Any

from clawclip.branching.diff import diff_branches
from clawclip.branching.storage import BranchStore, ConversationBranch

logger = logging.getLogger(__name__)


class BranchManager:
    """Orchestrates conversation branching: fork, merge, compare, and delete.

    Requires a :class:`BranchStore` for metadata persistence and a
    *db_session_factory* (async SQLAlchemy session factory) to access the
    ``ConversationMessage`` rows.
    """

    def __init__(self, store: BranchStore, db_session_factory: Any) -> None:
        self._store = store
        self._session_factory = db_session_factory

    # ── Fork ─────────────────────────────────────────────────────

    async def fork_conversation(
        self,
        conv_id: str,
        name: str,
        at_message_id: str | None = None,
    ) -> ConversationBranch:
        """Create a new branch forked from *conv_id*.

        If *at_message_id* is given the branch is conceptually forked at that
        message (recorded in metadata; actual message copying is left to the
        caller so that the storage layer is not over-coupled here).
        """
        branch = await self._store.create_branch(
            conv_id=conv_id,
            parent_id=None,
            name=name,
            forked_at=at_message_id,
        )
        logger.info(
            "Forked conversation %s → branch '%s' (%s)",
            conv_id,
            name,
            branch.id[:8],
        )
        return branch

    # ── Merge ────────────────────────────────────────────────────

    async def merge_branch(self, branch_id: str, target_conv_id: str) -> None:
        """Copy messages from *branch_id* into *target_conv_id*.

        Fetches all messages that belong to the branch's source conversation
        from the database and inserts them into the target conversation.
        Requires the db_session_factory to return an SQLAlchemy async session.
        """
        branch = await self._store.get_branch(branch_id)
        if branch is None:
            raise ValueError(f"Branch {branch_id!r} not found")

        try:
            from clawclip.storage.models.conversation import ConversationMessage
            from sqlalchemy import select

            async with self._session_factory() as session:
                result = await session.execute(
                    select(ConversationMessage).where(
                        ConversationMessage.conversation_id == branch.conversation_id
                    )
                )
                messages = result.scalars().all()

                for msg in messages:
                    new_msg = ConversationMessage(
                        conversation_id=target_conv_id,
                        role=msg.role,
                        content=msg.content,
                        platform_message_id=msg.platform_message_id,
                        agent_id=msg.agent_id,
                        provider=msg.provider,
                        model=msg.model,
                        tool_calls=msg.tool_calls,
                        token_count=msg.token_count,
                        cost_usd=msg.cost_usd,
                    )
                    session.add(new_msg)
                await session.commit()

            logger.info(
                "Merged branch %s (%d messages) → conversation %s",
                branch_id[:8],
                len(messages),
                target_conv_id,
            )
        except Exception as exc:
            logger.error("merge_branch failed: %s", exc)
            raise

    # ── Compare ──────────────────────────────────────────────────

    async def compare(self, branch_a_id: str, branch_b_id: str) -> dict[str, Any]:
        """Return a diff between messages of two branches."""
        branch_a = await self._store.get_branch(branch_a_id)
        branch_b = await self._store.get_branch(branch_b_id)
        if branch_a is None:
            raise ValueError(f"Branch {branch_a_id!r} not found")
        if branch_b is None:
            raise ValueError(f"Branch {branch_b_id!r} not found")

        messages_a = await self._get_messages(branch_a.conversation_id)
        messages_b = await self._get_messages(branch_b.conversation_id)
        return await diff_branches(messages_a, messages_b)

    # ── List / delete ─────────────────────────────────────────────

    async def list_branches(self, conv_id: str) -> list[ConversationBranch]:
        return await self._store.list_branches(conv_id)

    async def delete_branch(self, branch_id: str) -> None:
        await self._store.delete_branch(branch_id)

    # ── Internal ─────────────────────────────────────────────────

    async def _get_messages(self, conv_id: str) -> list[Any]:
        """Fetch conversation messages from DB, or return [] on error."""
        try:
            from clawclip.storage.models.conversation import ConversationMessage
            from sqlalchemy import select

            async with self._session_factory() as session:
                result = await session.execute(
                    select(ConversationMessage).where(
                        ConversationMessage.conversation_id == conv_id
                    )
                )
                return list(result.scalars().all())
        except Exception as exc:
            logger.error("_get_messages failed for %s: %s", conv_id, exc)
            return []
