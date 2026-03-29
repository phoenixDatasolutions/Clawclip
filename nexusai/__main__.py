"""NexusAI CLI entry point — nexusai run / setup / config / db."""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

import click
import structlog


def _setup_logging(level: str = "INFO") -> None:
    """Configure structured logging."""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.ConsoleRenderer(colors=True),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
    logging.basicConfig(level=getattr(logging, level.upper(), logging.INFO))


@click.group()
@click.version_option(package_name="nexusai")
def cli() -> None:
    """NexusAI — Modular Multi-Agent AI Platform."""
    pass


@cli.command()
@click.option("--config", default="config/local.yaml", help="Path to local config YAML")
@click.option("--log-level", default="INFO", help="Log level (DEBUG, INFO, WARNING, ERROR)")
def run(config: str, log_level: str) -> None:
    """Start NexusAI with all enabled platforms and services."""
    _setup_logging(log_level)

    from nexusai.app import NexusApp

    try:
        asyncio.run(NexusApp(config).run())
    except KeyboardInterrupt:
        click.echo("\nNexusAI stopped.")


@cli.command()
@click.option("--config-dir", default="config", help="Configuration directory")
def setup(config_dir: str) -> None:
    """Run the interactive setup wizard."""
    from nexusai.setup_wizard.wizard import run_wizard

    asyncio.run(run_wizard())


@cli.command("config")
@click.argument("action", type=click.Choice(["check", "show"]))
@click.option("--config-dir", default="config", help="Configuration directory")
def config_cmd(action: str, config_dir: str) -> None:
    """Check or show configuration."""
    from nexusai.core.config import NexusConfig

    config = NexusConfig(config_dir)

    if action == "check":
        try:
            config.load()
            click.echo("✓ Configuration loaded successfully")

            # Check platforms
            platforms = config.get("platforms", {})
            enabled = [k for k, v in platforms.items() if isinstance(v, dict) and v.get("enabled")]
            click.echo(f"  Platforms: {', '.join(enabled) if enabled else '(none enabled)'}")

            # Check providers
            providers = config.get("providers", {})
            enabled = [k for k, v in providers.items() if isinstance(v, dict) and v.get("enabled")]
            click.echo(f"  Providers: {', '.join(enabled) if enabled else '(none enabled)'}")

            # Check features
            features = config.get("features", {})
            enabled = [k for k, v in features.items() if isinstance(v, dict) and v.get("enabled")]
            click.echo(f"  Features:  {', '.join(enabled) if enabled else '(none enabled)'}")

        except Exception as e:
            click.echo(f"✗ Configuration error: {e}", err=True)
            sys.exit(1)

    elif action == "show":
        import yaml

        config.load()
        click.echo(yaml.dump(config.data, default_flow_style=False, sort_keys=False))


@cli.command()
@click.argument("action", type=click.Choice(["migrate", "reset"]))
@click.option("--config-dir", default="config", help="Configuration directory")
def db(action: str, config_dir: str) -> None:
    """Database management commands."""
    if action == "migrate":
        click.echo("Running database migrations...")
        import subprocess
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            click.echo("✓ Migrations complete")
        else:
            click.echo(f"✗ Migration failed:\n{result.stderr}", err=True)
            sys.exit(1)
    elif action == "reset":
        click.confirm("This will delete all data. Continue?", abort=True)
        click.echo("Resetting database...")
        # Will be implemented with storage layer


@cli.command("skills")
@click.argument("action", type=click.Choice(["list"]))
def skills_cmd(action: str) -> None:
    """Skill management commands."""
    if action == "list":
        click.echo("Built-in Skills:")
        skills = [
            ("shell", "Execute bash/PowerShell commands"),
            ("files", "File system operations (read, write, list, download)"),
            ("git", "Git version control (status, diff, commit, push, PR)"),
            ("monitor", "System monitoring (CPU, RAM, disk, processes)"),
            ("screenshot", "Desktop screenshot capture"),
            ("web_search", "Web search (Tavily, SerpAPI, Brave)"),
            ("services", "Windows services control"),
        ]
        for name, desc in skills:
            click.echo(f"  {name:15s} — {desc}")

        click.echo("\nDeveloper Skills:")
        dev_skills = [
            ("code_review", "AI-powered code review"),
            ("pr_management", "GitHub/GitLab PR management"),
            ("ci_cd", "CI/CD pipeline integration"),
            ("deployment", "Deployment automation"),
            ("log_analysis", "Log analysis and debugging"),
            ("db_ops", "Database operations"),
            ("api_testing", "API testing and validation"),
        ]
        for name, desc in dev_skills:
            click.echo(f"  {name:15s} — {desc}")


@cli.command("agents")
@click.argument("action", type=click.Choice(["list"]))
def agents_cmd(action: str) -> None:
    """Agent management commands."""
    if action == "list":
        click.echo("Built-in Agents:")
        agents = [
            ("coordinator", "Routes tasks to specialized agents"),
            ("code", "Code generation, review, and debugging"),
            ("research", "Web search and documentation research"),
            ("system", "Shell commands, monitoring, screenshots"),
            ("devops", "Git, CI/CD, deployment automation"),
        ]
        for name, desc in agents:
            click.echo(f"  {name:15s} — {desc}")


def main() -> None:
    """Entry point for the nexusai command."""
    cli()


if __name__ == "__main__":
    main()
