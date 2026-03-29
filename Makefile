.PHONY: install dev run setup test lint format clean docker-up docker-down

# One-step install
install:
	python -m venv .venv
	.venv/Scripts/pip install -e ".[minimal]"
	@echo "✓ Installed. Run 'make setup' to configure."

# Install with all features
install-all:
	python -m venv .venv
	.venv/Scripts/pip install -e ".[all,dev]"
	@echo "✓ Installed with all features."

# Dev install
dev:
	python -m venv .venv
	.venv/Scripts/pip install -e ".[all,dev]"
	@echo "✓ Dev environment ready."

# Interactive setup wizard
setup:
	.venv/Scripts/python -m nexusai setup

# Run the application
run:
	.venv/Scripts/python -m nexusai run

# Run tests
test:
	.venv/Scripts/pytest tests/ -v

# Lint
lint:
	.venv/Scripts/ruff check nexusai/ tests/

# Format
format:
	.venv/Scripts/ruff format nexusai/ tests/

# Database migrations
db-migrate:
	.venv/Scripts/alembic upgrade head

# Docker
docker-up:
	docker compose up -d --build

docker-down:
	docker compose down

# Clean
clean:
	rm -rf .venv __pycache__ .pytest_cache .mypy_cache .ruff_cache
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
