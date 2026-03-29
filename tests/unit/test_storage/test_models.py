"""Unit tests for ClawClip ORM models.

Tests cover:
- Unique constraints
- Automatic timestamp fields
- UUID primary keys
- Relationships between Conversation and ConversationMessage
- CostEntry creation and retrieval
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from clawclip.storage.database import Database
from clawclip.storage.models.cost import CostEntry
from clawclip.storage.models.conversation import Conversation, ConversationMessage
from clawclip.storage.models.user import User, UserPlatformLink


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def mem_db():
    db = Database("sqlite+aiosqlite:///:memory:")
    await db.initialize()
    yield db
    await db.close()


@pytest.fixture
async def session(mem_db: Database):
    async with mem_db.session() as s:
        yield s


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_user(session, **kwargs) -> User:
    defaults = {"display_name": "TestUser", "role": "user"}
    defaults.update(kwargs)
    user = User(**defaults)
    session.add(user)
    await session.flush()
    return user


# ---------------------------------------------------------------------------
# Unique constraint tests
# ---------------------------------------------------------------------------


class TestUniqueConstraints:
    async def test_user_platform_link_unique_constraint(self, mem_db: Database):
        """Inserting two UserPlatformLinks with the same (platform, platform_user_id)
        must raise IntegrityError."""
        async with mem_db.session() as s:
            user = await _create_user(s)
            link1 = UserPlatformLink(
                user_id=user.id,
                platform="telegram",
                platform_user_id="999",
            )
            s.add(link1)
            await s.flush()

        with pytest.raises(IntegrityError):
            async with mem_db.session() as s:
                # Re-fetch user in this session scope
                result = await s.execute(select(User))
                existing_user = result.scalars().first()
                link2 = UserPlatformLink(
                    user_id=existing_user.id,
                    platform="telegram",
                    platform_user_id="999",  # duplicate!
                )
                s.add(link2)
                await s.flush()

    async def test_different_platforms_same_id_allowed(self, mem_db: Database):
        """Same platform_user_id on different platforms must be permitted."""
        async with mem_db.session() as s:
            user = await _create_user(s)
            s.add(
                UserPlatformLink(
                    user_id=user.id, platform="telegram", platform_user_id="42"
                )
            )
            s.add(
                UserPlatformLink(
                    user_id=user.id, platform="discord", platform_user_id="42"
                )
            )
            # Should not raise
            await s.flush()


# ---------------------------------------------------------------------------
# Timestamp tests
# ---------------------------------------------------------------------------


class TestTimestamps:
    async def test_timestamp_auto_set(self, session):
        """created_at and updated_at must be populated after flush."""
        user = await _create_user(session)
        assert user.created_at is not None
        assert user.updated_at is not None

    async def test_conversation_timestamp_auto_set(self, session):
        """Conversation.created_at must be set automatically."""
        user = await _create_user(session)
        conv = Conversation(
            user_id=user.id,
            platform="telegram",
            channel_id="ch1",
        )
        session.add(conv)
        await session.flush()
        assert conv.created_at is not None
        assert conv.updated_at is not None


# ---------------------------------------------------------------------------
# UUID primary key tests
# ---------------------------------------------------------------------------


class TestUUIDPrimaryKey:
    async def test_uuid_primary_key(self, session):
        """Created model must have a valid UUID-4 string as its id."""
        user = await _create_user(session)
        assert user.id is not None
        # Validate it parses as UUID-4
        parsed = uuid.UUID(user.id, version=4)
        assert str(parsed) == user.id

    async def test_uuid_primary_key_unique(self, session):
        """Two separate model instances must receive different UUIDs."""
        u1 = await _create_user(session, display_name="Alice")
        u2 = await _create_user(session, display_name="Bob")
        assert u1.id != u2.id

    async def test_platform_link_uuid(self, session):
        """UserPlatformLink must also get a UUID primary key."""
        user = await _create_user(session)
        link = UserPlatformLink(
            user_id=user.id, platform="telegram", platform_user_id="tg_1"
        )
        session.add(link)
        await session.flush()
        assert link.id is not None
        parsed = uuid.UUID(link.id, version=4)
        assert str(parsed) == link.id


# ---------------------------------------------------------------------------
# Relationship tests
# ---------------------------------------------------------------------------


class TestRelationships:
    async def test_conversation_message_relationship(self, mem_db: Database):
        """Conversation.messages relationship must be populated correctly."""
        async with mem_db.session() as s:
            user = await _create_user(s)
            conv = Conversation(
                user_id=user.id,
                platform="telegram",
                channel_id="ch1",
            )
            s.add(conv)
            await s.flush()

            msg1 = ConversationMessage(
                conversation_id=conv.id,
                role="user",
                content="Hello!",
            )
            msg2 = ConversationMessage(
                conversation_id=conv.id,
                role="assistant",
                content="Hi there!",
            )
            s.add(msg1)
            s.add(msg2)
            await s.flush()
            conv_id = conv.id

        # Load the conversation with its messages in a fresh session
        async with mem_db.session() as s:
            from sqlalchemy.orm import selectinload

            result = await s.execute(
                select(Conversation)
                .where(Conversation.id == conv_id)
                .options(selectinload(Conversation.messages))
            )
            loaded_conv = result.scalar_one()
            assert len(loaded_conv.messages) == 2
            roles = {m.role for m in loaded_conv.messages}
            assert roles == {"user", "assistant"}

    async def test_user_platform_links_relationship(self, mem_db: Database):
        """User.platform_links must contain all associated platform links."""
        async with mem_db.session() as s:
            user = await _create_user(s)
            s.add(
                UserPlatformLink(
                    user_id=user.id, platform="telegram", platform_user_id="tg_42"
                )
            )
            s.add(
                UserPlatformLink(
                    user_id=user.id, platform="discord", platform_user_id="dc_42"
                )
            )
            await s.flush()
            user_id = user.id

        async with mem_db.session() as s:
            from sqlalchemy.orm import selectinload

            result = await s.execute(
                select(User)
                .where(User.id == user_id)
                .options(selectinload(User.platform_links))
            )
            loaded_user = result.scalar_one()
            assert len(loaded_user.platform_links) == 2
            platforms = {lnk.platform for lnk in loaded_user.platform_links}
            assert platforms == {"telegram", "discord"}

    async def test_cascade_delete_messages(self, mem_db: Database):
        """Deleting a Conversation must cascade-delete its messages."""
        async with mem_db.session() as s:
            user = await _create_user(s)
            conv = Conversation(
                user_id=user.id, platform="telegram", channel_id="ch_del"
            )
            s.add(conv)
            await s.flush()
            msg = ConversationMessage(
                conversation_id=conv.id, role="user", content="bye"
            )
            s.add(msg)
            await s.flush()
            msg_id = msg.id
            await s.delete(conv)
            await s.flush()

        async with mem_db.session() as s:
            loaded_msg = await s.get(ConversationMessage, msg_id)
            assert loaded_msg is None


# ---------------------------------------------------------------------------
# CostEntry tests
# ---------------------------------------------------------------------------


class TestCostEntry:
    async def test_cost_entry(self, mem_db: Database):
        """CostEntry must be persisted and retrievable with correct field values."""
        async with mem_db.session() as s:
            user = await _create_user(s)
            entry = CostEntry(
                user_id=user.id,
                provider="openai",
                model="gpt-4o",
                input_tokens=1000,
                output_tokens=250,
                cost_usd=0.0125,
            )
            s.add(entry)
            await s.flush()
            entry_id = entry.id

        async with mem_db.session() as s:
            loaded = await s.get(CostEntry, entry_id)
            assert loaded is not None
            assert loaded.provider == "openai"
            assert loaded.model == "gpt-4o"
            assert loaded.input_tokens == 1000
            assert loaded.output_tokens == 250
            assert abs(loaded.cost_usd - 0.0125) < 1e-9

    async def test_cost_entry_defaults(self, mem_db: Database):
        """CostEntry must apply default values when fields are omitted."""
        async with mem_db.session() as s:
            user = await _create_user(s)
            entry = CostEntry(
                user_id=user.id,
                provider="anthropic",
                model="claude-3-sonnet",
            )
            s.add(entry)
            await s.flush()
            assert entry.input_tokens == 0
            assert entry.output_tokens == 0
            assert entry.cost_usd == 0.0

    async def test_cost_entry_created_at_auto_set(self, mem_db: Database):
        """CostEntry.created_at must be set automatically."""
        async with mem_db.session() as s:
            user = await _create_user(s)
            entry = CostEntry(
                user_id=user.id,
                provider="anthropic",
                model="claude-3-sonnet",
            )
            s.add(entry)
            await s.flush()
            assert entry.created_at is not None
