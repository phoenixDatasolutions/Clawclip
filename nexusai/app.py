"""NexusAI Application — main bootstrap orchestrator."""

from __future__ import annotations

import asyncio
import logging
import signal
from pathlib import Path
from typing import Any

from nexusai.core.config import NexusConfig
from nexusai.core.di import Container
from nexusai.core.events import ConfigChanged, EventBus
from nexusai.core.registry import Registry

logger = logging.getLogger(__name__)


class NexusApp:
    """Main application class that wires together all NexusAI components.

    Lifecycle:
        1. __init__: Create config, event bus, DI container
        2. initialize(): Load config, init database, register components
        3. start(): Start all enabled platform adapters concurrently
        4. stop(): Graceful shutdown of all components
    """

    def __init__(self, config_dir: str | Path = "config") -> None:
        self.config = NexusConfig(config_dir)
        self.event_bus = EventBus()
        self.container = Container()
        self._running = False
        self._shutdown_event = asyncio.Event()

    async def initialize(self) -> None:
        """Load configuration and register all enabled components."""
        logger.info("Initializing NexusAI v%s", self._get_version())

        # Load configuration
        self.config.load()

        # Register core services in DI container
        self.container.register("config", self.config)
        self.container.register("event_bus", self.event_bus)

        # Create registries
        self.container.register("platform_registry", Registry("platforms"))
        self.container.register("provider_registry", Registry("providers"))
        self.container.register("skill_registry", Registry("skills"))
        self.container.register("agent_registry", Registry("agents"))

        # Initialize database
        await self._init_database()

        # Register enabled providers
        await self._register_providers()

        # Register enabled platforms
        await self._register_platforms()

        # Load skills
        await self._load_skills()

        # Load agent definitions
        await self._load_agents()

        # Wire message router
        self._wire_message_router()

        logger.info("NexusAI initialized successfully")

    async def start(self) -> None:
        """Start all enabled platform adapters and services."""
        self._running = True
        logger.info("Starting NexusAI...")

        # Set up signal handlers for graceful shutdown
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self._handle_signal)
            except NotImplementedError:
                # Windows doesn't support add_signal_handler
                pass

        tasks: list[asyncio.Task[Any]] = []

        # Start all enabled platform adapters
        platform_registry: Registry = self.container.resolve("platform_registry")
        for name, adapter in platform_registry:
            logger.info("Starting platform: %s", name)
            tasks.append(asyncio.create_task(
                self._run_adapter(name, adapter),
                name=f"platform:{name}",
            ))

        # Start dashboard if enabled
        if self.config.is_enabled("features.dashboard"):
            tasks.append(asyncio.create_task(
                self._start_dashboard(),
                name="dashboard",
            ))

        # Start scheduler if enabled
        if self.config.is_enabled("features.scheduler"):
            tasks.append(asyncio.create_task(
                self._start_scheduler(),
                name="scheduler",
            ))

        # Start webhook gateway if enabled
        if self.config.is_enabled("features.webhooks"):
            tasks.append(asyncio.create_task(
                self._start_webhook_gateway(),
                name="webhooks",
            ))

        # Start MCP server if enabled
        if self.config.is_enabled("features.mcp"):
            tasks.append(asyncio.create_task(
                self._start_mcp_server(),
                name="mcp",
            ))

        if not tasks:
            logger.warning("No platforms or services enabled! Enable at least one platform.")
            return

        enabled_platforms = platform_registry.names()
        logger.info(
            "NexusAI running with platforms: %s",
            ", ".join(enabled_platforms) if enabled_platforms else "(none)",
        )

        # Wait for shutdown signal
        await self._shutdown_event.wait()

        # Cancel all tasks
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def stop(self) -> None:
        """Gracefully shut down all components."""
        logger.info("Shutting down NexusAI...")
        self._running = False

        # Stop platform adapters
        platform_registry: Registry = self.container.resolve("platform_registry")
        for name, adapter in platform_registry:
            try:
                await adapter.stop()
                logger.info("Stopped platform: %s", name)
            except Exception:
                logger.exception("Error stopping platform: %s", name)

        # Close database connections
        if self.container.has("database"):
            db = self.container.resolve("database")
            if hasattr(db, "close"):
                await db.close()

        self._shutdown_event.set()
        logger.info("NexusAI stopped")

    def _handle_signal(self) -> None:
        """Handle OS signals for graceful shutdown."""
        logger.info("Received shutdown signal")
        asyncio.create_task(self.stop())

    async def _run_adapter(self, name: str, adapter: Any) -> None:
        """Run a platform adapter, handling exceptions."""
        try:
            await adapter.start()
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Platform adapter '%s' crashed", name)

    async def _init_database(self) -> None:
        """Initialize the database engine and run migrations."""
        db_url = self.config.get("database.url", "sqlite+aiosqlite:///nexusai.db")
        logger.info("Initializing database: %s", db_url.split("///")[-1] if "///" in db_url else db_url)
        # Database initialization will be implemented in Phase 1
        # For now, just log that it would happen

    async def _register_providers(self) -> None:
        """Register enabled LLM providers."""
        provider_registry: Registry = self.container.resolve("provider_registry")
        providers_config = self.config.get("providers", {})

        for name, provider_config in providers_config.items():
            if not isinstance(provider_config, dict):
                continue
            if not provider_config.get("enabled", False):
                continue
            logger.info("LLM provider enabled: %s", name)
            # Provider instantiation will be implemented in Phase 3
            # provider_registry.register(name, provider_instance)

    async def _register_platforms(self) -> None:
        """Register enabled platform adapters."""
        platform_registry: Registry = self.container.resolve("platform_registry")
        platforms_config = self.config.get("platforms", {})

        for name, platform_config in platforms_config.items():
            if not isinstance(platform_config, dict):
                continue
            if not platform_config.get("enabled", False):
                continue
            logger.info("Platform enabled: %s", name)
            # Platform instantiation will be implemented in Phase 2
            # platform_registry.register(name, adapter_instance)

    async def _load_skills(self) -> None:
        """Load and register enabled skills."""
        logger.debug("Loading skills...")
        # Skill loading will be implemented in Phase 4

    async def _load_agents(self) -> None:
        """Load agent definitions from config."""
        logger.debug("Loading agent definitions...")
        # Agent loading will be implemented in Phase 5

    def _wire_message_router(self) -> None:
        """Wire the message routing pipeline."""
        logger.debug("Wiring message router...")
        # Message router will be implemented in Phase 2

    async def _start_dashboard(self) -> None:
        """Start the WebUI dashboard."""
        logger.info("Starting dashboard on port %s", self.config.get("features.dashboard.port", 8080))
        # Dashboard will be implemented in Phase 11

    async def _start_scheduler(self) -> None:
        """Start the task scheduler."""
        logger.info("Starting scheduler...")
        # Scheduler will be implemented in Phase 12

    async def _start_webhook_gateway(self) -> None:
        """Start the webhook API gateway."""
        logger.info("Starting webhook gateway on port %s", self.config.get("features.webhooks.port", 8081))
        # Webhook gateway will be implemented in Phase 12

    async def _start_mcp_server(self) -> None:
        """Start the MCP server."""
        logger.info("Starting MCP server on port %s", self.config.get("features.mcp.server_port", 8090))
        # MCP server will be implemented in Phase 8

    @staticmethod
    def _get_version() -> str:
        from nexusai import __version__
        return __version__
