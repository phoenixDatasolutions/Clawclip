"""NexusApp — application bootstrap that initializes and wires all modules."""
from __future__ import annotations

import asyncio
import logging
import signal
from pathlib import Path
from typing import Any

from clawclip.core.config import NexusConfig
from clawclip.core.di import Container
from clawclip.core.events import EventBus
from clawclip.core.registry import Registry
from clawclip.storage.database import Database
from clawclip.skills.manager import SkillManager
from clawclip.skills.loader import SkillLoader
from clawclip.agents.engine import AgentEngine

logger = logging.getLogger(__name__)


class NexusApp:
    def __init__(self, config_path: str = "config/local.yaml") -> None:
        # Support both config_path and legacy config_dir kwarg
        self.config = NexusConfig(config_path)
        self.container = Container()
        self.event_bus = EventBus()
        self.db: Database | None = None
        self.skill_manager: SkillManager | None = None
        self.agent_engine: AgentEngine | None = None
        self.platforms: dict[str, Any] = {}
        self.providers: dict[str, Any] = {}
        # Optional modules
        self.dashboard_app = None
        self.scheduler_engine = None
        self.workflow_engine = None
        self.knowledge_manager = None
        self.mcp_server = None
        self.notification_engine = None
        self.audit_logger = None
        self.replay_recorder = None
        self.company_manager = None
        self._tasks: list[asyncio.Task] = []
        self._running = False

    async def initialize(self) -> None:
        cfg = self.config
        logger.info("Initializing ClawClip...")

        # ── 1. Database ────────────────────────────────────────────
        db_url = cfg.get("storage.database_url", "sqlite+aiosqlite:///data/clawclip.db")
        Path("data").mkdir(exist_ok=True)
        self.db = Database(db_url)
        await self.db.initialize()
        self.container.register("db", self.db)
        logger.info("Database initialized: %s", db_url)

        # ── 2. Skills ──────────────────────────────────────────────
        self.skill_manager = SkillManager()
        loader = SkillLoader()
        for skill in loader.discover_builtin_skills():
            self.skill_manager.register(skill)
        if cfg.get("features.developer_skills.enabled", True):
            for skill in loader.discover_developer_skills():
                self.skill_manager.register(skill)
        self.container.register("skill_manager", self.skill_manager)
        logger.info("Skills loaded: %d registered", len(self.skill_manager.list_skills()))

        # ── 3. LLM Providers ───────────────────────────────────────
        await self._init_providers()

        # ── 4. Agent Engine ────────────────────────────────────────
        default_provider = next(iter(self.providers.values()), None)
        self.agent_engine = AgentEngine(
            skill_manager=self.skill_manager,
            provider=default_provider,
            event_bus=self.event_bus,
        )
        self.container.register("agent_engine", self.agent_engine)
        logger.info("Agent engine initialized")

        # ── 5. Security ────────────────────────────────────────────
        from clawclip.security.audit import AuditLogger
        self.audit_logger = AuditLogger(
            self.event_bus,
            self.db.session_factory if hasattr(self.db, "session_factory") else None,
        )
        await self.audit_logger.start()

        # ── 6. Optional modules ────────────────────────────────────
        await self._init_optional_modules()

        # ── 7. Platforms ───────────────────────────────────────────
        await self._init_platforms()

        # ── 8. Dashboard ───────────────────────────────────────────
        if cfg.get("features.dashboard.enabled", True):
            await self._init_dashboard()

        logger.info("ClawClip initialized successfully")

    async def _init_providers(self) -> None:
        cfg = self.config
        if cfg.get("providers.claude_api.enabled", False):
            try:
                from clawclip.providers.claude_api import ClaudeAPIProvider
                p = ClaudeAPIProvider(
                    api_key=cfg.get("providers.claude_api.api_key", ""),
                    default_model=cfg.get("providers.claude_api.default_model", "claude-opus-4-6"),
                )
                self.providers["claude-api"] = p
                logger.info("Provider registered: claude-api")
            except Exception as e:
                logger.warning("claude-api provider failed: %s", e)

        if cfg.get("providers.openai.enabled", False):
            try:
                from clawclip.providers.openai_ import OpenAIProvider
                p = OpenAIProvider(api_key=cfg.get("providers.openai.api_key", ""))
                self.providers["openai"] = p
                logger.info("Provider registered: openai")
            except Exception as e:
                logger.warning("openai provider failed: %s", e)

        if cfg.get("providers.ollama.enabled", False):
            try:
                from clawclip.providers.ollama import OllamaProvider
                p = OllamaProvider(
                    base_url=cfg.get("providers.ollama.base_url", "http://localhost:11434")
                )
                self.providers["ollama"] = p
                logger.info("Provider registered: ollama")
            except Exception as e:
                logger.warning("ollama provider failed: %s", e)

        if cfg.get("providers.gemini.enabled", False):
            try:
                from clawclip.providers.gemini import GeminiProvider
                p = GeminiProvider(api_key=cfg.get("providers.gemini.api_key", ""))
                self.providers["gemini"] = p
                logger.info("Provider registered: gemini")
            except Exception as e:
                logger.warning("gemini provider failed: %s", e)

        if cfg.get("providers.claude_cli.enabled", False):
            try:
                from clawclip.providers.claude_cli import ClaudeCLIProvider
                p = ClaudeCLIProvider()
                self.providers["claude-cli"] = p
                logger.info("Provider registered: claude-cli")
            except Exception as e:
                logger.warning("claude-cli provider failed: %s", e)

        if cfg.get("providers.litellm.enabled", False):
            try:
                from clawclip.providers.litellm_ import LiteLLMProvider
                p = LiteLLMProvider()
                self.providers["litellm"] = p
                logger.info("Provider registered: litellm")
            except Exception as e:
                logger.warning("litellm provider failed: %s", e)

        if not self.providers:
            logger.warning("No LLM providers configured — agents will not function")

    async def _init_optional_modules(self) -> None:
        cfg = self.config

        # Replay / Debug
        if cfg.get("features.replay_debug.enabled", True):
            try:
                from clawclip.replay.recorder import ExecutionRecorder
                self.replay_recorder = ExecutionRecorder(self.event_bus)
                await self.replay_recorder.start()
                logger.info("Replay recorder started")
            except Exception as e:
                logger.warning("Replay recorder failed: %s", e)

        # Knowledge Base (RAG)
        if cfg.get("features.knowledge_base.enabled", False):
            try:
                from clawclip.knowledge.manager import KnowledgeManager
                from clawclip.knowledge.embeddings import create_embedding_provider
                from clawclip.knowledge.vectorstore import create_vector_store
                from clawclip.knowledge.indexer import DocumentIndexer
                from clawclip.knowledge.retriever import Retriever
                emb = create_embedding_provider(cfg.get("features.knowledge_base", {}))
                vs = create_vector_store(cfg.get("features.knowledge_base", {}))
                indexer = DocumentIndexer(vs, emb)
                retriever = Retriever(vs, emb)
                self.knowledge_manager = KnowledgeManager(indexer, retriever)
                logger.info("Knowledge base initialized")
            except Exception as e:
                logger.warning("Knowledge base failed: %s", e)

        # Workflow Engine
        if cfg.get("features.workflows.enabled", False):
            try:
                from clawclip.workflows.engine import WorkflowEngine
                from clawclip.workflows.triggers import TriggerManager
                trigger_mgr = TriggerManager()
                default_provider = next(iter(self.providers.values()), None)
                self.workflow_engine = WorkflowEngine(
                    skill_manager=self.skill_manager,
                    llm_provider=default_provider,
                    trigger_manager=trigger_mgr,
                )
                workflow_dir = cfg.get("features.workflows.workflow_dir", "config/workflows")
                if Path(workflow_dir).exists():
                    await self.workflow_engine.load_workflows(workflow_dir)
                logger.info("Workflow engine initialized")
            except Exception as e:
                logger.warning("Workflow engine failed: %s", e)

        # Scheduler
        if cfg.get("features.scheduler.enabled", False):
            try:
                from clawclip.scheduler.engine import SchedulerEngine
                from clawclip.scheduler.store import JobStore
                store = JobStore()
                self.scheduler_engine = SchedulerEngine(
                    job_store=store,
                    agent_engine=self.agent_engine,
                    workflow_engine=self.workflow_engine,
                    skill_manager=self.skill_manager,
                )
                await self.scheduler_engine.start()
                logger.info("Scheduler started")
            except Exception as e:
                logger.warning("Scheduler failed: %s", e)

        # Notifications
        if cfg.get("features.notifications.enabled", False):
            try:
                from clawclip.notifications.engine import NotificationEngine
                from clawclip.notifications.rules import RulesEngine
                from clawclip.notifications.channels import LogNotificationChannel
                rules = RulesEngine([])
                channels = {"log": LogNotificationChannel()}
                self.notification_engine = NotificationEngine(channels, rules, self.event_bus)
                await self.notification_engine.start()
                logger.info("Notification engine started")
            except Exception as e:
                logger.warning("Notifications failed: %s", e)

        # MCP
        if cfg.get("features.mcp.enabled", False):
            try:
                from clawclip.mcp.server import MCPServer
                self.mcp_server = MCPServer(
                    skill_manager=self.skill_manager,
                    host=cfg.get("features.mcp.host", "0.0.0.0"),
                    port=cfg.get("features.mcp.server_port", 8090),
                )
                logger.info("MCP server configured (starts on app.start())")
            except Exception as e:
                logger.warning("MCP server failed: %s", e)

        # Company (Paperclip-style)
        if cfg.get("features.company.enabled", False):
            try:
                from clawclip.company.manager import CompanyManager
                self.company_manager = CompanyManager(
                    event_bus=self.event_bus,
                    agent_engine=self.agent_engine,
                )
                logger.info("Company manager initialized")
            except Exception as e:
                logger.warning("Company manager failed: %s", e)

    async def _init_platforms(self) -> None:
        cfg = self.config

        if cfg.get("platforms.telegram.enabled", False):
            try:
                from clawclip.platforms.telegram.adapter import TelegramAdapter
                adapter = TelegramAdapter(
                    config={
                        "token": cfg.get("platforms.telegram.bot_token", ""),
                        "allowed_users": cfg.get("platforms.telegram.allowed_users", []),
                    },
                    event_bus=self.event_bus,
                )
                self.platforms["telegram"] = adapter
                logger.info("Telegram adapter configured")
            except Exception as e:
                logger.warning("Telegram adapter failed: %s", e)

        if cfg.get("platforms.discord.enabled", False):
            try:
                from clawclip.platforms.discord.adapter import DiscordAdapter
                adapter = DiscordAdapter(
                    token=cfg.get("platforms.discord.token", ""),
                    event_bus=self.event_bus,
                )
                self.platforms["discord"] = adapter
                logger.info("Discord adapter configured")
            except Exception as e:
                logger.warning("Discord adapter failed: %s", e)

        if cfg.get("platforms.slack.enabled", False):
            try:
                from clawclip.platforms.slack.adapter import SlackAdapter
                adapter = SlackAdapter(
                    bot_token=cfg.get("platforms.slack.bot_token", ""),
                    signing_secret=cfg.get("platforms.slack.signing_secret", ""),
                    event_bus=self.event_bus,
                )
                self.platforms["slack"] = adapter
                logger.info("Slack adapter configured")
            except Exception as e:
                logger.warning("Slack adapter failed: %s", e)

        if cfg.get("platforms.cli.enabled", False):
            try:
                from clawclip.platforms.cli.adapter import CLIAdapter
                adapter = CLIAdapter(event_bus=self.event_bus)
                self.platforms["cli"] = adapter
                logger.info("CLI adapter configured")
            except Exception as e:
                logger.warning("CLI adapter failed: %s", e)

    async def _init_dashboard(self) -> None:
        try:
            from clawclip.dashboard.app import create_dashboard_app
            self.dashboard_app = create_dashboard_app(nexus_app=self)
            logger.info("Dashboard app created")
        except Exception as e:
            logger.warning("Dashboard failed: %s", e)

    async def start(self) -> None:
        """Start all platforms and background services."""
        self._running = True
        logger.info("Starting ClawClip...")

        # Start platforms
        for name, platform in self.platforms.items():
            try:
                task = asyncio.create_task(platform.start(), name=f"platform_{name}")
                self._tasks.append(task)
                logger.info("Platform started: %s", name)
            except Exception as e:
                logger.error("Platform %s failed to start: %s", name, e)

        # Start MCP server
        if self.mcp_server:
            try:
                await self.mcp_server.start()
            except Exception as e:
                logger.warning("MCP server start failed: %s", e)

        # Start dashboard server
        if self.dashboard_app:
            cfg = self.config
            host = cfg.get("features.dashboard.host", "0.0.0.0")
            port = cfg.get("features.dashboard.port", 8080)
            try:
                import uvicorn
                config = uvicorn.Config(self.dashboard_app, host=host, port=port, log_level="warning")
                server = uvicorn.Server(config)
                task = asyncio.create_task(server.serve(), name="dashboard")
                self._tasks.append(task)
                logger.info("Dashboard running at http://%s:%d", host, port)
            except ImportError:
                logger.warning("uvicorn not installed — dashboard not started")
            except Exception as e:
                logger.warning("Dashboard start failed: %s", e)

        logger.info("ClawClip is running. Press Ctrl+C to stop.")

    async def stop(self) -> None:
        """Graceful shutdown."""
        if not self._running:
            return
        self._running = False
        logger.info("Shutting down ClawClip...")

        # Stop platforms
        for name, platform in self.platforms.items():
            try:
                await platform.stop()
                logger.info("Platform stopped: %s", name)
            except Exception as e:
                logger.warning("Platform %s stop error: %s", name, e)

        # Cancel background tasks
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

        # Stop optional modules
        if self.scheduler_engine:
            try:
                await self.scheduler_engine.stop()
            except Exception:
                pass

        if self.notification_engine:
            try:
                await self.notification_engine.stop()
            except Exception:
                pass

        if self.mcp_server:
            try:
                await self.mcp_server.stop()
            except Exception:
                pass

        if self.replay_recorder:
            try:
                await self.replay_recorder.stop()
            except Exception:
                pass

        if self.audit_logger:
            try:
                await self.audit_logger.stop()
            except Exception:
                pass

        # Close DB
        if self.db:
            try:
                await self.db.close()
            except Exception:
                pass

        logger.info("ClawClip stopped.")

    def setup_signal_handlers(self) -> None:
        """Register SIGINT/SIGTERM handlers for graceful shutdown."""
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, lambda: asyncio.create_task(self.stop()))
            except (NotImplementedError, RuntimeError):
                pass  # Windows doesn't support add_signal_handler

    async def run(self) -> None:
        """Full lifecycle: initialize → start → wait → stop."""
        await self.initialize()
        self.setup_signal_handlers()
        await self.start()
        try:
            while self._running:
                await asyncio.sleep(1)
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
        finally:
            await self.stop()
