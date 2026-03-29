"""Cross-platform user resolution and authentication helpers."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from clawclip.core.types import PlatformUser
from clawclip.storage.models.user import User, UserPlatformLink

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class AuthManager:
    """Resolves platform identities to canonical User records."""

    async def resolve_user(self, platform_user: PlatformUser, session: AsyncSession) -> User:
        """Return the User for a platform identity, creating one on first visit.

        Looks up UserPlatformLink by (platform, platform_user_id). If no link
        exists, creates a new User and UserPlatformLink in the same transaction.
        """
        link = await self.get_platform_link(
            platform_user.platform, platform_user.platform_user_id, session
        )
        if link is not None:
            return link.user

        # First visit — create canonical user and platform link.
        user = User(
            display_name=platform_user.display_name or platform_user.username,
            role="user",
            is_active=True,
        )
        session.add(user)
        await session.flush()

        link = UserPlatformLink(
            user_id=user.id,
            platform=platform_user.platform,
            platform_user_id=platform_user.platform_user_id,
            platform_username=platform_user.username,
        )
        session.add(link)
        await session.flush()

        logger.info(
            "Created new user %s for %s/%s",
            user.id,
            platform_user.platform,
            platform_user.platform_user_id,
        )
        return user

    async def get_platform_link(
        self,
        platform: str,
        platform_user_id: str,
        session: AsyncSession,
    ) -> UserPlatformLink | None:
        """Return the UserPlatformLink for a (platform, platform_user_id) pair."""
        stmt = (
            select(UserPlatformLink)
            .where(
                UserPlatformLink.platform == platform,
                UserPlatformLink.platform_user_id == platform_user_id,
            )
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_user_by_platform(
        self,
        platform: str,
        platform_user_id: str,
        session: AsyncSession,
    ) -> User | None:
        """Return the User for a platform identity, or None if not registered."""
        link = await self.get_platform_link(platform, platform_user_id, session)
        if link is None:
            return None
        return await session.get(User, link.user_id)

    async def is_admin(self, user_id: str, session: AsyncSession) -> bool:
        """Return True if the user has the admin role."""
        user = await session.get(User, user_id)
        return user is not None and user.role == "admin"

    async def is_allowed(
        self,
        user_id: str,
        session: AsyncSession,
        config: dict,
    ) -> bool:
        """Return True if user_id is in the config allowed_users list.

        Falls back to True (allow all) if no allowed_users key is configured.
        Admins are always allowed.
        """
        if await self.is_admin(user_id, session):
            return True

        allowed: list[str] | None = config.get("allowed_users")
        if allowed is None:
            return True

        user = await session.get(User, user_id)
        if user is None or not user.is_active:
            return False

        return user_id in allowed
