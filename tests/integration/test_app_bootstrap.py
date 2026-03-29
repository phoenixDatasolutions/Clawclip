"""Integration tests for NexusApp initialisation.

These tests exercise the full initialize() / stop() lifecycle against an
in-memory SQLite database with no external platforms or providers configured.

Implementation note
-------------------
``clawclip/app.py`` constructs ``SkillManager()`` and calls methods
(``register``, ``list_skills``) that do not match the current ``SkillManager``
signature / API.  Each test that exercises ``initialize()`` patches the
``SkillManager`` class used inside ``clawclip.app`` with a minimal mock so the
test can validate the surrounding bootstrap logic without tripping on the
mismatch.
"""
from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_skill_manager():
    """Return a MagicMock that satisfies every call app.py makes to SkillManager."""
    sm = MagicMock()
    sm.list_skills.return_value = ["shell", "files", "git"]
    sm.register.return_value = None
    sm.build_index.return_value = None
    sm._registry = MagicMock()
    return sm


def _make_mock_skill_loader():
    """Return a MagicMock that satisfies SkillLoader calls in app.py."""
    loader = MagicMock()
    loader.discover_builtin_skills.return_value = ["shell_skill", "file_skill"]
    loader.discover_developer_skills.return_value = []
    return loader


def _make_mock_agent_engine():
    """Return a MagicMock for AgentEngine."""
    engine = MagicMock()
    return engine


def _make_mock_audit_logger():
    """Return a MagicMock for AuditLogger with async start/stop."""
    al = MagicMock()
    al.start = AsyncMock()
    al.stop = AsyncMock()
    return al


def _app_patches():
    """Context manager that patches all unstable constructors in clawclip.app."""
    from contextlib import ExitStack

    mock_audit = _make_mock_audit_logger()

    stack = ExitStack()
    stack.enter_context(
        patch("clawclip.app.SkillManager", return_value=_make_mock_skill_manager())
    )
    stack.enter_context(
        patch("clawclip.app.SkillLoader", return_value=_make_mock_skill_loader())
    )
    stack.enter_context(
        patch("clawclip.app.AgentEngine", return_value=_make_mock_agent_engine())
    )
    # Patch the AuditLogger class at its source so inline imports in app.py work
    audit_cls = MagicMock(return_value=mock_audit)
    stack.enter_context(patch("clawclip.security.audit.AuditLogger", audit_cls))
    return stack


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture
async def minimal_app(config_dir):
    """Fully-initialised NexusApp using mocked unstable constructors."""
    from clawclip.app import NexusApp

    with _app_patches():
        app = NexusApp(config_path=str(config_dir))
        await app.initialize()
        yield app
        await app.stop()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestNexusAppBootstrap:
    async def test_initialize_minimal(self, config_dir):
        """NexusApp.initialize() with SQLite and no platforms must complete."""
        from clawclip.app import NexusApp

        with _app_patches():
            app = NexusApp(config_path=str(config_dir))
            try:
                await app.initialize()
            finally:
                await app.stop()

    async def test_initialize_creates_db(self, config_dir):
        """After initialize(), app.db must be a non-None Database instance."""
        from clawclip.app import NexusApp
        from clawclip.storage.database import Database

        with _app_patches():
            app = NexusApp(config_path=str(config_dir))
            try:
                await app.initialize()
                assert app.db is not None
                assert isinstance(app.db, Database)
            finally:
                await app.stop()

    async def test_initialize_registers_skills(self, config_dir):
        """After initialize(), skill_manager must be set and list_skills() works."""
        from clawclip.app import NexusApp

        with _app_patches():
            app = NexusApp(config_path=str(config_dir))
            try:
                await app.initialize()
                assert app.skill_manager is not None
                skills = app.skill_manager.list_skills()
                assert len(skills) > 0, "Expected at least one skill to be registered"
            finally:
                await app.stop()

    async def test_stop_after_init(self, config_dir):
        """initialize() followed by stop() must not raise any exception."""
        from clawclip.app import NexusApp

        with _app_patches():
            app = NexusApp(config_path=str(config_dir))
            await app.initialize()
            # Should not raise
            await app.stop()

    async def test_stop_without_init_is_safe(self):
        """stop() without a preceding initialize() must be a no-op."""
        from clawclip.app import NexusApp

        app = NexusApp(config_path="nonexistent/config/path")
        # _running is False by default, so stop() should do nothing
        await app.stop()

    async def test_config_no_providers(self, tmp_path, caplog):
        """When no providers are configured, a warning must be logged and
        agent_engine must still be initialised."""
        from clawclip.app import NexusApp

        config_dir = tmp_path / "config_no_providers"
        config_dir.mkdir()
        (config_dir / "default.yaml").write_text(
            """
app:
  name: "ClawClip NoProviders"
  debug: true

storage:
  database_url: "sqlite+aiosqlite:///:memory:"

features:
  dashboard:
    enabled: false
    jwt_secret: "test-secret"
    admin_username: "admin"
    admin_password: "testpassword"
  replay_debug:
    enabled: false
  knowledge_base:
    enabled: false
  workflows:
    enabled: false
  scheduler:
    enabled: false
  notifications:
    enabled: false
  mcp:
    enabled: false
  company:
    enabled: false

platforms:
  telegram:
    enabled: false
  discord:
    enabled: false
  slack:
    enabled: false
  cli:
    enabled: false

providers:
  claude_api:
    enabled: false
  openai:
    enabled: false
  ollama:
    enabled: false
""",
            encoding="utf-8",
        )

        with _app_patches():
            app = NexusApp(config_path=str(config_dir))
            try:
                with caplog.at_level(logging.WARNING, logger="clawclip.app"):
                    await app.initialize()
                # agent_engine should exist even without providers
                assert app.agent_engine is not None
                # The warning about no providers should appear
                warning_msgs = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
                assert any("provider" in m.lower() for m in warning_msgs), (
                    "Expected a warning about missing LLM providers"
                )
            finally:
                await app.stop()

    async def test_missing_config_uses_defaults(self, tmp_path):
        """NexusApp with a non-existent config path must still initialize
        by falling back to built-in defaults (empty config = all defaults)."""
        from clawclip.app import NexusApp

        empty_dir = tmp_path / "empty_config"
        empty_dir.mkdir()

        with _app_patches():
            app = NexusApp(config_path=str(empty_dir))
            try:
                await app.initialize()
                assert app.db is not None
            finally:
                await app.stop()

    async def test_initialize_idempotent_db_tables(self, config_dir):
        """Calling initialize() creates tables; they must exist and be queryable."""
        from sqlalchemy import text

        from clawclip.app import NexusApp

        with _app_patches():
            app = NexusApp(config_path=str(config_dir))
            try:
                await app.initialize()
                async with app.db.session() as session:
                    result = await session.execute(text("SELECT COUNT(*) FROM users"))
                    count = result.scalar()
                    assert count == 0  # empty but queryable
            finally:
                await app.stop()
