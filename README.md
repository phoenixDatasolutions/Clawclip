<div align="center">

```
 ██████╗██╗      █████╗ ██╗    ██╗ ██████╗██╗     ██╗██████╗
██╔════╝██║     ██╔══██╗██║    ██║██╔════╝██║     ██║██╔══██╗
██║     ██║     ███████║██║ █╗ ██║██║     ██║     ██║██████╔╝
██║     ██║     ██╔══██║██║███╗██║██║     ██║     ██║██╔═══╝
╚██████╗███████╗██║  ██║╚███╔███╔╝╚██████╗███████╗██║██║
 ╚═════╝╚══════╝╚═╝  ╚═╝ ╚══╝╚══╝  ╚═════╝╚══════╝╚═╝╚═╝
```

**Multi-Agent AI Platform — Any LLM. Any Chat App. One Command.**

[![Python](https://img.shields.io/badge/Python-3.12%2B-blue?style=flat-square&logo=python)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-green?style=flat-square)](LICENSE)
[![Tests](https://img.shields.io/badge/Tests-419%20passing-brightgreen?style=flat-square)](tests/)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-red?style=flat-square)](https://docs.astral.sh/ruff/)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen?style=flat-square)](CONTRIBUTING.md)

[Quick Start](#quick-start) · [Features](#features) · [Architecture](#architecture) · [Configuration](#configuration) · [Contributing](#contributing)

</div>

---

ClawClip is a **self-hosted, open-source AI agent platform** that connects your messaging apps to powerful AI models through a multi-agent orchestration engine. Think of it as having a team of AI specialists — a coder, a researcher, a sysadmin, a DevOps engineer — all working together on your tasks, coordinated automatically.

```
You: "Review my PR, run the tests, and deploy if they pass"
     ↓
ClawClip: Coordinator breaks the task down and runs agents in parallel
     ├── Code Agent    → reviews the diff, checks for issues
     ├── DevOps Agent  → runs CI pipeline, watches test results
     └── System Agent  → monitors resources during the run
     ↓
You: "✅ PR approved. 42/42 tests pass. Deployed to staging at 14:32."
```

---

## Features

### Platforms
| Platform | Status | Notes |
|----------|--------|-------|
| Telegram | ✅ Full | Streaming, inline buttons, FSM chat mode |
| Discord | ✅ Full | Slash commands, threads, button views |
| Slack | ✅ Full | Socket Mode, Block Kit, slash commands |
| Web UI | ✅ Full | FastAPI + WebSocket, built-in chat |
| CLI | ✅ Full | Rich terminal output, stdin/stdout |
| WhatsApp | 🔜 Stub | Business API bridge |
| Signal | 🔜 Stub | signal-cli bridge |
| Matrix | 🔜 Stub | matrix-nio |

### AI Providers
| Provider | Status |
|----------|--------|
| Claude API (Anthropic) | ✅ |
| Claude CLI | ✅ |
| OpenAI / GPT | ✅ |
| Google Gemini | ✅ |
| Ollama (local) | ✅ |
| LiteLLM (proxy) | ✅ |
| Any OpenAI-compatible API | ✅ |

### Core Features
- **Multi-Agent Orchestration** — Coordinator decomposes tasks into a DAG and runs specialized agents in parallel
- **14+ Skills** — Shell, Files, Git, System Monitor, Screenshots, Web Search, Code Review, CI/CD, Deployment, DB Ops, API Testing, QA, Automation
- **RAG Knowledge Base** — Index your codebase, docs, or web pages; agents query it automatically
- **MCP Protocol** — Expose ClawClip skills to Claude Desktop/VS Code; consume external MCP servers
- **Workflow Engine** — YAML-defined pipelines with webhook, cron, and event triggers
- **Web Dashboard** — Real-time agent status, cost analytics, feature toggles, user management
- **Self-Healing Agents** — 4-stage retry: rephrase → different model → different agent → escalate to human
- **Docker Sandboxing** — Isolated code execution with resource limits
- **Conversation Branching** — Fork at any point, compare approaches, merge the best result
- **Replay & Debug** — Full execution traces, step-through inspection, HTML export
- **Company / Org Mode** — Org chart, ticket system, per-agent budgets, governance rules, audit log
- **Scheduled Tasks** — APScheduler-based cron jobs for recurring agent work
- **Notification Engine** — Alert routing across all connected platforms with digest mode
- **Webhook Gateway** — Receive GitHub/GitLab/generic webhooks, route to agents or workflows
- **Teams & Workspaces** — Multi-user with role hierarchy (owner / admin / member / viewer)

---

## Quick Start

### Option 1 — One command (recommended)

```bash
git clone https://github.com/yourname/clawclip.git
cd clawclip
./setup.sh
```

The setup wizard walks you through everything interactively — no YAML editing required.

### Option 2 — Manual

```bash
git clone https://github.com/yourname/clawclip.git
cd clawclip

# Create virtual environment
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Linux / Mac

# Install (choose your extras)
pip install -e ".[minimal]"   # Telegram + Claude + Dashboard
pip install -e ".[all]"       # Everything

# Configure and start
clawclip setup   # Interactive wizard → writes config/local.yaml
clawclip run     # Start the platform
```

### Option 3 — Docker

```bash
git clone https://github.com/yourname/clawclip.git
cd clawclip
cp .env.example .env    # Add your API keys
docker compose up -d
```

Dashboard available at `http://localhost:8080`.

---

## Install Extras

```bash
# Platforms
pip install -e ".[telegram]"
pip install -e ".[discord]"
pip install -e ".[slack]"

# AI Providers
pip install -e ".[claude-api]"
pip install -e ".[openai]"
pip install -e ".[gemini]"

# Features
pip install -e ".[dashboard]"
pip install -e ".[knowledge]"
pip install -e ".[scheduler]"
pip install -e ".[mcp-support]"
pip install -e ".[sandbox]"

# Bundles
pip install -e ".[minimal]"   # Telegram + Claude + Dashboard
pip install -e ".[all]"       # Everything
```

---

## CLI Commands

```bash
clawclip run              # Start the platform
clawclip setup            # Re-run setup wizard
clawclip config check     # Validate your config
clawclip config show      # Print merged config
clawclip db migrate       # Run database migrations
clawclip skills list      # List all available skills
clawclip agents list      # List all available agents
```

---

## Skill Triggers (use directly in chat)

```
/sh ls -la                   → Shell command
/git status                  → Git status
/test                        → Run test suite
/test tests/unit             → Run specific tests
/coverage clawclip           → Get coverage report
/lint                        → Lint with ruff
/ci                          → Full CI pipeline
/report                      → Generate QA Markdown report
/watch                       → Watch files and re-run tests on change
```

---

## Architecture

```
User Message (Telegram / Discord / Slack / Web / CLI)
        │
        ▼
 PlatformAdapter  ──►  EventBus  ──►  MessageRouter
                                            │
                         ┌──────────────────┤
                         │                  │
                    Skill trigger?      Free-text prompt
                         │                  │
                    SkillManager       RAG augments context
                         │                  │
                    SkillResult        AgentEngine.execute_task_stream()
                                            │
                                    CoordinatorAgent
                                            │
                                      TaskPlanner (DAG)
                                            │
                            ┌───────────────┼───────────────┐
                            ▼               ▼               ▼
                        CodeAgent    ResearchAgent    DevOpsAgent
                       (parallel)     (parallel)      (parallel)
                            │               │               │
                     Shell/Files/Git   WebSearch/RAG    CI/CD/Deploy
                            │               │               │
                            └───────────────┴───────────────┘
                                            │
                                   Self-Healing (on failure)
                                   rephrase → new model → new agent
                                            │
                                    CostEntry recorded
                                            │
                            PlatformAdapter.stream_response()
                                            │
                                        User ✓
```

---

## Configuration

ClawClip uses a **two-file config system**:

| File | Purpose |
|------|---------|
| `config/default.yaml` | Shipped defaults — never edit this |
| `config/local.yaml` | Your overrides — auto-generated by wizard |

Every feature has an `enabled: true/false` toggle. Changes to `local.yaml` hot-reload without restart. The Web Dashboard Settings page exposes all toggles as switches.

```yaml
# config/local.yaml example
platforms:
  telegram:
    enabled: true
    bot_token: "your-token"

providers:
  claude_api:
    enabled: true
    api_key: "${ANTHROPIC_API_KEY}"

features:
  knowledge_base:
    enabled: true
    vector_store: "chromadb"
  dashboard:
    enabled: true
    port: 8080
```

---

## Project Structure

```
clawclip/
├── core/            # Types, events, interfaces, config, DI container
├── platforms/       # Telegram, Discord, Slack, WebUI, CLI adapters
├── providers/       # Claude, OpenAI, Gemini, Ollama, LiteLLM
├── agents/          # Engine, Coordinator, Code, Research, System, DevOps
├── skills/          # 14+ built-in + developer skills
├── storage/         # SQLAlchemy models + repositories
├── security/        # Auth, RBAC, rate limiter, vault, audit log
├── company/         # Org chart, tickets, budgets, governance
├── knowledge/       # RAG — loaders, embeddings, vector store, retriever
├── mcp/             # MCP server + client + bridge
├── workflows/       # YAML pipeline engine
├── dashboard/       # FastAPI REST API + WebSocket + frontend
├── scheduler/       # APScheduler cron engine
├── notifications/   # Alert routing + digest mode
├── webhooks/        # GitHub/GitLab/generic webhook gateway
├── sandbox/         # Docker sandboxing
├── branching/       # Conversation fork/merge
├── replay/          # Execution trace recorder + HTML exporter
├── healing/         # Self-healing retry strategies
├── teams/           # Multi-user workspaces + roles
└── setup_wizard/    # Interactive terminal setup wizard
```

---

## Running Tests

```bash
pip install -e ".[test]"
pytest                          # All 419 tests
pytest tests/unit               # Unit tests only
pytest tests/integration        # Integration tests only
pytest -m "not slow"            # Skip slow tests
```

No API keys needed — all external calls are faked.

---

## Contributing

1. Fork the repo
2. `pip install -e ".[dev]"` — installs ruff, mypy, pytest, pre-commit
3. `pre-commit install`
4. Make your changes
5. `pytest` — ensure all tests pass
6. Open a PR

See [docs/contributing.md](docs/contributing.md) for detailed guidelines.

---

## Roadmap

- [ ] React frontend for the Web Dashboard
- [ ] Skills marketplace (remote discovery + one-click install)
- [ ] WhatsApp, Signal, Matrix full adapters
- [ ] Microsoft Teams adapter
- [ ] Cloud deploy templates (Railway, Render, Fly.io)
- [ ] Mobile app (React Native)
- [ ] Voice interface (Whisper + TTS)

---

## License

MIT — see [LICENSE](LICENSE) for details.

---

<div align="center">
Built with ❤️ · <a href="https://github.com/yourname/clawclip/issues">Report a bug</a> · <a href="https://github.com/yourname/clawclip/discussions">Discussions</a>
</div>
