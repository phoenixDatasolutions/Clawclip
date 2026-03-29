"""Unit tests for clawclip.storage.repositories.base.BaseRepository.

All tests use an in-memory SQLite database and the User / UserPlatformLink
models as concrete examples of the generic repository.
"""
from __future__ import annotations

import pytest

from clawclip.storage.database import Database
from clawclip.storage.models.user import User, UserPlatformLink
from clawclip.storage.repositories.base import BaseRepository


# ---------------------------------------------------------------------------
# Concrete repository classes for tests
# ---------------------------------------------------------------------------


class UserRepository(BaseRepository[User]):
    model_class = User


class PlatformLinkRepository(BaseRepository[UserPlatformLink]):
    model_class = UserPlatformLink


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
    """Yield a single open session for the duration of the test."""
    async with mem_db.session() as s:
        yield s


@pytest.fixture
def user_repo(session):
    return UserRepository(session)


@pytest.fixture
def link_repo(session):
    return PlatformLinkRepository(session)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(**kwargs) -> dict:
    base = {"display_name": "Test User", "role": "user"}
    base.update(kwargs)
    return base


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCreate:
    async def test_create_user(self, user_repo: UserRepository):
        """create() must return an instance with an auto-assigned UUID id."""
        user = await user_repo.create(**_make_user())
        assert user.id is not None
        assert len(user.id) == 36  # UUID4 string

    async def test_create_sets_defaults(self, user_repo: UserRepository):
        """create() must honour model-level column defaults."""
        user = await user_repo.create(display_name="Grace")
        assert user.role == "user"
        assert user.is_active is True


class TestGet:
    async def test_get_user(self, user_repo: UserRepository):
        """get(id) after create() must return the same record."""
        user = await user_repo.create(**_make_user(display_name="Alice"))
        loaded = await user_repo.get(user.id)
        assert loaded is not None
        assert loaded.id == user.id
        assert loaded.display_name == "Alice"

    async def test_get_missing(self, user_repo: UserRepository):
        """get('nonexistent-id') must return None, not raise."""
        result = await user_repo.get("nonexistent-id")
        assert result is None


class TestList:
    async def test_list_users(self, user_repo: UserRepository):
        """list_() must return all created records."""
        for i in range(3):
            await user_repo.create(display_name=f"User{i}")
        users = await user_repo.list_()
        assert len(users) == 3

    async def test_list_empty(self, user_repo: UserRepository):
        """list_() on an empty table must return []."""
        result = await user_repo.list_()
        assert result == []

    async def test_list_with_filter(self, user_repo: UserRepository):
        """list_() with keyword filter must narrow results."""
        await user_repo.create(display_name="Admin1", role="admin")
        await user_repo.create(display_name="User1", role="user")
        admins = await user_repo.list_(role="admin")
        assert len(admins) == 1
        assert admins[0].display_name == "Admin1"

    async def test_list_with_limit(self, user_repo: UserRepository):
        """list_(limit=2) must return at most 2 records."""
        for i in range(5):
            await user_repo.create(display_name=f"U{i}")
        result = await user_repo.list_(limit=2)
        assert len(result) == 2

    async def test_list_with_offset(self, user_repo: UserRepository):
        """list_(offset=2) must skip the first 2 records."""
        for i in range(4):
            await user_repo.create(display_name=f"U{i}")
        all_users = await user_repo.list_()
        paged = await user_repo.list_(offset=2)
        assert len(paged) == 2
        assert paged[0].id == all_users[2].id


class TestUpdate:
    async def test_update_user(self, user_repo: UserRepository):
        """update(id, ...) must persist the new values."""
        user = await user_repo.create(display_name="OldName")
        updated = await user_repo.update(user.id, display_name="NewName")
        assert updated is not None
        assert updated.display_name == "NewName"

    async def test_update_missing(self, user_repo: UserRepository):
        """update('nonexistent-id', ...) must return None, not raise."""
        result = await user_repo.update("nonexistent-id", display_name="X")
        assert result is None

    async def test_update_multiple_fields(self, user_repo: UserRepository):
        """update() must handle multiple kwargs simultaneously."""
        user = await user_repo.create(display_name="Old", role="user")
        updated = await user_repo.update(user.id, display_name="New", role="admin")
        assert updated.display_name == "New"
        assert updated.role == "admin"


class TestDelete:
    async def test_delete_user(self, user_repo: UserRepository):
        """delete(id) must remove the record so get() returns None."""
        user = await user_repo.create(display_name="ToDelete")
        deleted = await user_repo.delete(user.id)
        assert deleted is True
        result = await user_repo.get(user.id)
        assert result is None

    async def test_delete_missing(self, user_repo: UserRepository):
        """delete('nonexistent-id') must return False, not raise."""
        result = await user_repo.delete("nonexistent-id")
        assert result is False


class TestCount:
    async def test_count(self, user_repo: UserRepository):
        """count() must equal the number of rows inserted."""
        for _ in range(5):
            await user_repo.create(display_name="User")
        total = await user_repo.count()
        assert total == 5

    async def test_count_empty(self, user_repo: UserRepository):
        """count() on an empty table must return 0."""
        assert await user_repo.count() == 0

    async def test_count_with_filter(self, user_repo: UserRepository):
        """count(role='admin') must count only matching rows."""
        await user_repo.create(display_name="A1", role="admin")
        await user_repo.create(display_name="A2", role="admin")
        await user_repo.create(display_name="U1", role="user")
        admin_count = await user_repo.count(role="admin")
        assert admin_count == 2


class TestGetBy:
    async def test_get_by_field(self, user_repo: UserRepository):
        """get_by(field=value) must return the first matching record."""
        await user_repo.create(display_name="Match", role="admin")
        await user_repo.create(display_name="Other", role="user")
        result = await user_repo.get_by(role="admin")
        assert result is not None
        assert result.display_name == "Match"

    async def test_get_by_no_match(self, user_repo: UserRepository):
        """get_by() with no matching rows must return None."""
        await user_repo.create(display_name="User", role="user")
        result = await user_repo.get_by(role="superadmin")
        assert result is None

    async def test_get_by_multiple_fields(self, user_repo: UserRepository):
        """get_by(field1=v1, field2=v2) must apply all filters."""
        await user_repo.create(display_name="AdminActive", role="admin", is_active=True)
        await user_repo.create(display_name="AdminInactive", role="admin", is_active=False)
        result = await user_repo.get_by(role="admin", is_active=False)
        assert result is not None
        assert result.display_name == "AdminInactive"
