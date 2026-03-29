# Contributing to ClawClip

Thank you for considering a contribution. ClawClip is MIT-licensed and welcomes pull requests, bug reports, and feature ideas.

---

## Table of Contents

- [Local Setup](#local-setup)
- [Project Layout](#project-layout)
- [Coding Standards](#coding-standards)
- [Running Tests](#running-tests)
- [Submitting a Pull Request](#submitting-a-pull-request)
- [Reporting Bugs](#reporting-bugs)
- [Suggesting Features](#suggesting-features)

---

## Local Setup

### Requirements

- Python 3.12 or higher
- Git

### Steps

```bash
# 1. Fork the repo on GitHub, then clone your fork
git clone https://github.com/YOUR_USERNAME/clawclip.git
cd clawclip

# 2. Create a virtual environment
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Linux / Mac

# 3. Install in editable mode with dev dependencies
pip install -e ".[dev,test]"

# 4. Install pre-commit hooks
pre-commit install

# 5. Copy the example env file
cp .env.example .env
```

That's it. No API keys are required to run the test suite — all external calls are faked.

### Verifying the setup

```bash
python -c "from clawclip.core.events import EventBus; print('OK')"
pytest tests/unit -q
```

Both should complete without errors.

---

## Project Layout

```
clawclip/           Main Python package
├── core/           Types, events, config, registry, DI container
├── platforms/      Messaging adapters (Telegram, Discord, Slack, …)
├── providers/      LLM adapters (Claude, OpenAI, Ollama, …)
├── agents/         Multi-agent orchestration engine
├── skills/         Skill / plugin system
├── storage/        SQLAlchemy models and repositories
├── security/       Auth, RBAC, rate limiting, vault
├── company/        Org chart, tickets, budgets, governance
├── dashboard/      FastAPI REST + WebSocket control panel
└── …

tests/
├── unit/           Fast, no I/O — run these constantly during development
└── integration/    Spin up in-process FastAPI / SQLite — run before a PR

config/
├── default.yaml    Shipped defaults — never edit this file
└── local.yaml      Your overrides — git-ignored
```

New modules follow the same pattern: a `Protocol`-based interface in `core/interfaces/`, an implementation in the appropriate subpackage, and unit tests alongside.

---

## Coding Standards

### Formatter and linter — ruff

ClawClip uses [ruff](https://docs.astral.sh/ruff/) for both formatting and linting. The pre-commit hook runs it automatically. To run manually:

```bash
ruff check .          # lint
ruff check --fix .    # lint + auto-fix
ruff format .         # format
```

Key rules enforced: `E`, `F`, `I` (isort), `N` (naming), `W`, `UP` (pyupgrade), `B` (bugbear), `SIM`, `TCH`.

### Type hints — mypy strict

All public functions and methods must be fully type-annotated. The CI runs `mypy --strict`:

```bash
mypy clawclip
```

Common patterns used throughout the codebase:

```python
from __future__ import annotations          # at the top of every file
from typing import Any
from collections.abc import AsyncGenerator

async def execute(self, task: TaskRequest) -> AgentResult: ...
async def stream(self) -> AsyncGenerator[str, None]: ...
```

### Async-first

All I/O must be async. Never use blocking calls (`time.sleep`, `open()`, `requests`) inside async functions. Use `asyncio.create_subprocess_exec` for subprocesses, `aiofiles` for file I/O, `httpx.AsyncClient` for HTTP.

### No global state

Use the dependency injection container (`core/di.py`) or pass dependencies explicitly. Singletons and module-level mutable state make testing difficult.

### Optional dependencies

Any import that requires an optional package must be guarded:

```python
try:
    import discord
except ImportError:
    discord = None  # type: ignore[assignment]
```

Never add a hard dependency to `[dependencies]` in `pyproject.toml` for something that only one adapter uses. Put it in the appropriate extras group.

### Docstrings

Public classes and methods get a one-line docstring. Keep it factual — describe what the thing does, not how.

```python
class ShellSkill:
    """Execute shell commands and return stdout/stderr."""
```

No docstrings on private helpers (`_run_command`, etc.) unless the logic is genuinely non-obvious.

---

## Running Tests

```bash
pytest                          # all 419 tests
pytest tests/unit               # unit tests only (fast, ~8s)
pytest tests/integration        # integration tests (~4s)
pytest -m "not slow"            # skip slow tests
pytest tests/unit/test_agents   # single module
pytest -x                       # stop on first failure
pytest --tb=short               # shorter tracebacks
```

### Test markers

| Marker | When to use |
|--------|-------------|
| `@pytest.mark.unit` | Pure unit test, no I/O |
| `@pytest.mark.integration` | Uses in-process server or real DB |
| `@pytest.mark.slow` | Takes > 5 seconds |
| `@pytest.mark.requires_docker` | Needs Docker daemon |
| `@pytest.mark.requires_telegram` | Needs a real Telegram token |

### Writing tests

- Use the shared fixtures from `tests/conftest.py` — `event_bus`, `fake_provider`, `agent_engine`, `db`, etc.
- Prefer `FakeLLMProvider` over mocking the provider class directly.
- Keep unit tests free of filesystem I/O — use `tmp_path` when you need files.
- Integration tests for the dashboard use `httpx.AsyncClient` with `ASGITransport` — no port binding needed.

---

## Submitting a Pull Request

### Before you start

For anything beyond a small bug fix, open an issue first to discuss the approach. This avoids wasted effort if the direction doesn't fit the project.

### Workflow

```bash
# 1. Sync your fork with upstream
git remote add upstream https://github.com/yourname/clawclip.git
git fetch upstream
git rebase upstream/main

# 2. Create a branch — use a descriptive name
git checkout -b feat/discord-threads
git checkout -b fix/rate-limiter-overflow
git checkout -b docs/contributing-guide

# 3. Make your changes, commit often
git add <files>
git commit -m "feat(discord): support thread replies"

# 4. Push and open a PR
git push origin feat/discord-threads
```

Then open a pull request against `main` on GitHub.

### PR checklist

Before submitting, make sure:

- [ ] `pytest` passes with no failures
- [ ] `ruff check .` has no errors
- [ ] `mypy clawclip` has no errors
- [ ] New behaviour is covered by tests
- [ ] Public API changes are reflected in docstrings
- [ ] Optional dependencies are properly guarded with `try/except ImportError`
- [ ] `config/default.yaml` is updated if you added a new config key

### Commit message format

```
<type>(<scope>): <short summary>

<optional body>
```

Types: `feat`, `fix`, `docs`, `test`, `refactor`, `chore`, `ci`

Examples:
```
feat(skills): add DatabaseOpsSkill with query and migrate tools
fix(rate-limiter): reset bucket correctly on window expiry
docs(readme): add Docker deployment section
test(agents): cover coordinator delegation depth limit
```

### What to expect

- A maintainer will review within a few days.
- Small, focused PRs get reviewed faster than large ones.
- If changes are requested, push new commits to the same branch — do not force-push after review has started.

---

## Reporting Bugs

Open an issue and include:

1. ClawClip version (`clawclip --version`)
2. Python version and OS
3. Minimal steps to reproduce
4. What you expected vs what happened
5. Relevant log output (redact any API keys)

---

## Suggesting Features

Open a GitHub Discussion or issue with the `enhancement` label. Describe the use case — not just the feature — so we can understand what problem it solves.

---

## Questions?

Open a [GitHub Discussion](https://github.com/yourname/clawclip/discussions). Issues are for bugs and confirmed feature requests.
