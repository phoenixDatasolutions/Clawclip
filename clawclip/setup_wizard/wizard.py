"""ClawClip Interactive Setup Wizard — guided terminal experience."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import questionary
import yaml
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

console = Console()


def run_wizard(config_dir: str = "config") -> None:
    """Run the interactive setup wizard."""
    config_path = Path(config_dir)
    config_path.mkdir(parents=True, exist_ok=True)

    console.print()
    console.print(
        Panel.fit(
            "[bold cyan]ClawClip Setup Wizard[/bold cyan]\n\n"
            "This wizard will help you configure ClawClip.\n"
            "Your choices will be saved to [yellow]config/local.yaml[/yellow].",
            border_style="cyan",
        )
    )
    console.print()

    # Step 1: System check
    _step_system_check()

    # Step 2: Choose platforms
    platforms = _step_platforms()

    # Step 3: Choose LLM providers
    providers = _step_providers()

    # Step 4: Choose features
    features = _step_features()

    # Step 5: Security setup
    security = _step_security(platforms)

    # Step 6: Build and save config
    config = _build_config(platforms, providers, features, security)
    _save_config(config, config_path)

    # Step 7: Summary
    _step_summary(platforms, providers, features, config_path)


def _step_system_check() -> None:
    """Check system requirements."""
    console.print("[bold]Step 1/6: System Check[/bold]")
    console.print()

    # Python version
    py_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    if sys.version_info >= (3, 12):
        console.print(f"  [green]✓[/green] Python {py_version}")
    else:
        console.print(f"  [red]✗[/red] Python {py_version} (3.12+ required)")
        sys.exit(1)

    # Docker
    if shutil.which("docker"):
        console.print("  [green]✓[/green] Docker found (sandbox features available)")
    else:
        console.print("  [yellow]○[/yellow] Docker not found (sandbox will use local execution)")

    # Git
    if shutil.which("git"):
        console.print("  [green]✓[/green] Git found")
    else:
        console.print("  [yellow]○[/yellow] Git not found (git skills will be limited)")

    console.print()


def _step_platforms() -> dict:
    """Choose messaging platforms."""
    console.print("[bold]Step 2/6: Messaging Platforms[/bold]")
    console.print("  Which messaging apps do you want to connect?")
    console.print()

    platform_choices = [
        questionary.Choice("Telegram", value="telegram"),
        questionary.Choice("Discord", value="discord"),
        questionary.Choice("Slack", value="slack"),
        questionary.Choice("WhatsApp (Business API)", value="whatsapp"),
        questionary.Choice("Signal", value="signal"),
        questionary.Choice("Matrix", value="matrix"),
        questionary.Choice("Web UI (browser-based chat)", value="webui"),
        questionary.Choice("CLI (terminal interface)", value="cli"),
    ]

    selected = questionary.checkbox(
        "Select platforms (Space to toggle, Enter to confirm):",
        choices=platform_choices,
    ).ask()

    if not selected:
        console.print("  [yellow]No platforms selected. You can enable them later in the dashboard.[/yellow]")
        return {}

    result = {}
    for platform in selected:
        result[platform] = {"enabled": True}

        if platform == "telegram":
            token = questionary.text(
                "  Telegram Bot Token:",
                instruction="(Get from @BotFather on Telegram)",
            ).ask()
            if token:
                result[platform]["bot_token"] = token

            user_ids = questionary.text(
                "  Your Telegram User ID:",
                instruction="(Send /myid to @userinfobot)",
            ).ask()
            if user_ids:
                result[platform]["allowed_user_ids"] = user_ids

        elif platform == "discord":
            token = questionary.text(
                "  Discord Bot Token:",
                instruction="(From Discord Developer Portal)",
            ).ask()
            if token:
                result[platform]["bot_token"] = token

        elif platform == "slack":
            token = questionary.text("  Slack Bot Token:").ask()
            if token:
                result[platform]["bot_token"] = token
            app_token = questionary.text("  Slack App Token:").ask()
            if app_token:
                result[platform]["app_token"] = app_token

        elif platform == "whatsapp":
            api_url = questionary.text("  WhatsApp API URL:").ask()
            if api_url:
                result[platform]["api_url"] = api_url
            api_token = questionary.text("  WhatsApp API Token:").ask()
            if api_token:
                result[platform]["api_token"] = api_token

    console.print()
    return result


def _step_providers() -> dict:
    """Choose LLM providers."""
    console.print("[bold]Step 3/6: AI Models[/bold]")
    console.print("  Which AI models do you want to use?")
    console.print()

    provider_choices = [
        questionary.Choice("Claude (Anthropic API)", value="claude_api"),
        questionary.Choice("Claude CLI (local Claude Code)", value="claude_cli"),
        questionary.Choice("OpenAI / GPT", value="openai"),
        questionary.Choice("Google Gemini", value="gemini"),
        questionary.Choice("Ollama (local models)", value="ollama"),
        questionary.Choice("LiteLLM (unified proxy)", value="litellm"),
        questionary.Choice("OpenAI-compatible API", value="openai_compat"),
    ]

    selected = questionary.checkbox(
        "Select providers (Space to toggle, Enter to confirm):",
        choices=provider_choices,
    ).ask()

    if not selected:
        console.print("  [yellow]No providers selected. You can add them later in the dashboard.[/yellow]")
        return {}

    result = {}
    for provider in selected:
        result[provider] = {"enabled": True}

        if provider == "claude_api":
            key = questionary.password(
                "  Anthropic API Key:",
                instruction="(From console.anthropic.com)",
            ).ask()
            if key:
                result[provider]["api_key"] = key

        elif provider == "openai":
            key = questionary.password(
                "  OpenAI API Key:",
                instruction="(From platform.openai.com)",
            ).ask()
            if key:
                result[provider]["api_key"] = key

        elif provider == "gemini":
            key = questionary.password(
                "  Google API Key:",
                instruction="(From aistudio.google.com)",
            ).ask()
            if key:
                result[provider]["api_key"] = key

        elif provider == "ollama":
            url = questionary.text(
                "  Ollama URL:",
                default="http://localhost:11434",
            ).ask()
            if url:
                result[provider]["base_url"] = url

        elif provider == "openai_compat":
            url = questionary.text("  API Base URL:").ask()
            if url:
                result[provider]["base_url"] = url
            key = questionary.password("  API Key (if required):").ask()
            if key:
                result[provider]["api_key"] = key

    console.print()
    return result


def _step_features() -> dict:
    """Choose which features to enable."""
    console.print("[bold]Step 4/6: Features[/bold]")
    console.print("  Which features do you want to enable?")
    console.print("  (You can toggle these anytime in the Web Dashboard)")
    console.print()

    feature_choices = [
        questionary.Choice(
            "Multi-Agent Orchestration (agents collaborate on tasks)",
            value="multi_agent",
            checked=True,
        ),
        questionary.Choice(
            "Web Dashboard (control panel in your browser)",
            value="dashboard",
            checked=True,
        ),
        questionary.Choice(
            "Replay & Debug (record and inspect agent execution)",
            value="replay_debug",
            checked=True,
        ),
        questionary.Choice(
            "Self-Healing Agents (auto-retry on failures)",
            value="self_healing",
            checked=True,
        ),
        questionary.Choice(
            "Knowledge Base (RAG — index docs for agent context)",
            value="knowledge_base",
        ),
        questionary.Choice(
            "Workflow Engine (YAML-defined automation pipelines)",
            value="workflows",
        ),
        questionary.Choice(
            "Scheduled Tasks (cron-based recurring jobs)",
            value="scheduler",
        ),
        questionary.Choice(
            "Webhook Gateway (receive webhooks from GitHub, etc.)",
            value="webhooks",
        ),
        questionary.Choice(
            "Notifications (proactive alerts across platforms)",
            value="notifications",
        ),
        questionary.Choice(
            "Multi-User & Teams (shared workspaces)",
            value="teams",
        ),
        questionary.Choice(
            "Docker Sandbox (isolated code execution)",
            value="docker_sandbox",
        ),
        questionary.Choice(
            "Conversation Branching (fork/merge like git)",
            value="conversation_branching",
        ),
        questionary.Choice(
            "MCP Protocol (connect to external MCP servers)",
            value="mcp",
        ),
    ]

    selected = questionary.checkbox(
        "Select features (Space to toggle, Enter to confirm):",
        choices=feature_choices,
    ).ask()

    result = {}
    for feature in selected or []:
        result[feature] = {"enabled": True}

    console.print()
    return result


def _step_security(platforms: dict) -> dict:
    """Set up basic security."""
    console.print("[bold]Step 5/6: Security[/bold]")
    console.print()

    result: dict = {}

    # Dashboard password
    password = questionary.password(
        "  Dashboard admin password:",
        instruction="(For the web dashboard login)",
    ).ask()
    if password:
        result["dashboard_password"] = password

    # Admin user IDs
    admin_ids: list[str] = []
    for platform_name, platform_config in platforms.items():
        if platform_name == "telegram" and platform_config.get("allowed_user_ids"):
            admin_ids.append(platform_config["allowed_user_ids"])

    if admin_ids:
        result["admin_ids"] = admin_ids

    console.print()
    return result


def _build_config(
    platforms: dict,
    providers: dict,
    features: dict,
    security: dict,
) -> dict:
    """Build the final config/local.yaml content."""
    config: dict = {
        "platforms": {},
        "providers": {},
        "features": {},
        "security": {
            "auth": {
                "admin_ids": security.get("admin_ids", []),
            },
        },
    }

    # Platforms
    for name, settings in platforms.items():
        config["platforms"][name] = settings

    # Providers
    for name, settings in providers.items():
        config["providers"][name] = settings

    # Features
    for name, settings in features.items():
        config["features"][name] = settings

    # Dashboard password
    if security.get("dashboard_password"):
        if "dashboard" not in config["features"]:
            config["features"]["dashboard"] = {"enabled": True}
        config["features"]["dashboard"]["admin_password"] = security["dashboard_password"]

    return config


def _save_config(config: dict, config_path: Path) -> None:
    """Save the config to local.yaml and .env."""
    local_yaml = config_path / "local.yaml"

    # Extract secrets for .env file
    env_vars: dict[str, str] = {}

    # Extract platform tokens
    for platform, settings in config.get("platforms", {}).items():
        if platform == "telegram":
            if settings.get("bot_token"):
                env_vars["TELEGRAM_BOT_TOKEN"] = settings.pop("bot_token")
            if settings.get("allowed_user_ids"):
                env_vars["ALLOWED_TELEGRAM_IDS"] = settings.pop("allowed_user_ids")
        elif platform == "discord":
            if settings.get("bot_token"):
                env_vars["DISCORD_BOT_TOKEN"] = settings.pop("bot_token")
        elif platform == "slack":
            if settings.get("bot_token"):
                env_vars["SLACK_BOT_TOKEN"] = settings.pop("bot_token")
            if settings.get("app_token"):
                env_vars["SLACK_APP_TOKEN"] = settings.pop("app_token")

    # Extract provider API keys
    for provider, settings in config.get("providers", {}).items():
        if provider == "claude_api" and settings.get("api_key"):
            env_vars["ANTHROPIC_API_KEY"] = settings.pop("api_key")
        elif provider == "openai" and settings.get("api_key"):
            env_vars["OPENAI_API_KEY"] = settings.pop("api_key")
        elif provider == "gemini" and settings.get("api_key"):
            env_vars["GOOGLE_API_KEY"] = settings.pop("api_key")

    # Extract dashboard password
    dashboard = config.get("features", {}).get("dashboard", {})
    if dashboard.get("admin_password"):
        env_vars["DASHBOARD_ADMIN_PASSWORD"] = dashboard.pop("admin_password")

    # Write local.yaml (without secrets)
    with open(local_yaml, "w", encoding="utf-8") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    # Write .env file with secrets
    env_file = Path(".env")
    env_lines = ["# Auto-generated by ClawClip setup wizard", ""]
    for key, value in env_vars.items():
        env_lines.append(f"{key}={value}")
    env_lines.append("")

    with open(env_file, "w", encoding="utf-8") as f:
        f.write("\n".join(env_lines))

    console.print(f"  [green]✓[/green] Config saved to [yellow]{local_yaml}[/yellow]")
    console.print(f"  [green]✓[/green] Secrets saved to [yellow].env[/yellow]")


def _step_summary(
    platforms: dict,
    providers: dict,
    features: dict,
    config_path: Path,
) -> None:
    """Show setup summary."""
    console.print("[bold]Step 6/6: Summary[/bold]")
    console.print()

    table = Table(show_header=True, header_style="bold cyan", border_style="dim")
    table.add_column("Category", style="bold")
    table.add_column("Enabled")

    # Platforms
    platform_names = list(platforms.keys()) if platforms else ["(none)"]
    table.add_row("Platforms", ", ".join(platform_names))

    # Providers
    provider_names = list(providers.keys()) if providers else ["(none)"]
    table.add_row("AI Models", ", ".join(provider_names))

    # Features
    feature_names = list(features.keys()) if features else ["(none)"]
    table.add_row("Features", ", ".join(feature_names))

    console.print(table)
    console.print()

    console.print(
        Panel.fit(
            "[bold green]Setup Complete![/bold green]\n\n"
            "Start ClawClip:\n"
            "  [cyan]clawclip run[/cyan]\n"
            "  — or —\n"
            "  [cyan]make run[/cyan]\n\n"
            "Change settings anytime:\n"
            "  [cyan]clawclip setup[/cyan]  (CLI wizard)\n"
            "  [cyan]http://localhost:8080[/cyan]  (Web Dashboard)",
            border_style="green",
        )
    )
