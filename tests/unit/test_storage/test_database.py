"""Unit tests for nexusai.storage.database.Database."""
from __future__ import annotations

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncSession

from nexusai.storage.database import Database


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def mem_db():
    """Fresh in-memory SQLite database for each test."""
    db = Database("sqlite+aiosqlite:///:memory:")
    await db.initialize()
    yield db
    await db.close()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDatabaseInitialize:
    async def test_initialize_creates_tables(self, mem_db: Database):
        """After initialize(), all expected tables must exist in the schema."""
        async with mem_db.engine.connect() as conn:
            table_names = await conn.run_sync(
                lambda sync_conn: inspect(sync_conn).get_table_names()
            )

        expected_tables = {
            "users",
            "user_platform_links",
            "conversations",
            "conversation_messages",
            "llm_sessions",
            "cost_entries",
        }
        for table in expected_tables:
            assert table in table_names, f"Expected table '{table}' not found"

    async def test_engine_accessible_after_init(self, mem_db: Database):
        """engine property must be accessible after initialize()."""
        engine = mem_db.engine
        assert engine is not None

    async def test_engine_raises_before_init(self):
        """engine property must raise RuntimeError before initialize()."""
        db = Database("sqlite+aiosqlite:///:memory:")
        with pytest.raises(RuntimeError, match="not initialized"):
            _ = db.engine

    async def test_session_raises_before_init(self):
        """session() context manager must raise RuntimeError before initialize()."""
        db = Database("sqlite+aiosqlite:///:memory:")
        with pytest.raises(RuntimeError, match="not initialized"):
            async with db.session():
                pass


class TestDatabaseSession:
    async def test_session_context_manager(self, mem_db: Database):
        """session() must yield a usable AsyncSession."""
        async with mem_db.session() as session:
            assert isinstance(session, AsyncSession)
            # Exercise the session with a simple query
            result = await session.execute(text("SELECT 1"))
            assert result.scalar() == 1

    async def test_session_commits_on_success(self, mem_db: Database):
        """Data written inside a successful session block must be persisted."""
        from nexusai.storage.models.user import User

        # Write a user inside one session
        user_id: str = ""
        async with mem_db.session() as session:
            user = User(display_name="Alice", role="user")
            session.add(user)
            await session.flush()
            user_id = user.id

        # Read it back in a fresh session
        async with mem_db.session() as session:
            loaded = await session.get(User, user_id)
            assert loaded is not None
            assert loaded.display_name == "Alice"

    async def test_session_rolls_back_on_error(self, mem_db: Database):
        """An exception inside the session block must trigger a rollback."""
        from nexusai.storage.models.user import User

        user_id: str = ""
        with pytest.raises(ValueError, match="oops"):
            async with mem_db.session() as session:
                user = User(display_name="Bob", role="user")
                session.add(user)
                await session.flush()
                user_id = user.id
                raise ValueError("oops")  # trigger rollback

        # The user must NOT be visible after the rollback
        async with mem_db.session() as session:
            loaded = await session.get(User, user_id)
            assert loaded is None

    async def test_multiple_sessions_independent(self, mem_db: Database):
        """Two independent sessions must not interfere with each other."""
        from nexusai.storage.models.user import User

        async with mem_db.session() as s1:
            u1 = User(display_name="S1User", role="user")
            s1.add(u1)
            await s1.flush()
            id1 = u1.id

        async with mem_db.session() as s2:
            u2 = User(display_name="S2User", role="admin")
            s2.add(u2)
            await s2.flush()
            id2 = u2.id

        async with mem_db.session() as verify:
            r1 = await verify.get(User, id1)
            r2 = await verify.get(User, id2)
            assert r1 is not None
            assert r2 is not None
            assert r1.display_name == "S1User"
            assert r2.display_name == "S2User"
