FROM python:3.12-slim AS base

WORKDIR /app

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY pyproject.toml ./
COPY nexusai/ nexusai/
COPY config/ config/
COPY alembic.ini ./
COPY alembic/ alembic/

# Install with all features
RUN pip install --no-cache-dir -e ".[all]"

# Create data directory
RUN mkdir -p /app/data

# Default port for dashboard
EXPOSE 8080

# Environment
ENV PYTHONUNBUFFERED=1
ENV NEXUSAI_DATA_DIR=/app/data
ENV NEXUSAI_CONFIG_DIR=/app/config

# Entrypoint
CMD ["python", "-m", "nexusai", "run"]
