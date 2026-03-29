#!/usr/bin/env bash
# NexusAI One-Step Installer
# Usage: git clone <repo> && cd nexusai && ./setup.sh

set -e

echo "╔══════════════════════════════════════════════╗"
echo "║         NexusAI — One-Step Installer         ║"
echo "╚══════════════════════════════════════════════╝"
echo ""

# Check Python version
PYTHON_CMD=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        version=$("$cmd" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null)
        major=$("$cmd" -c "import sys; print(sys.version_info.major)" 2>/dev/null)
        minor=$("$cmd" -c "import sys; print(sys.version_info.minor)" 2>/dev/null)
        if [ "$major" -ge 3 ] && [ "$minor" -ge 12 ]; then
            PYTHON_CMD="$cmd"
            echo "✓ Found Python $version ($cmd)"
            break
        fi
    fi
done

if [ -z "$PYTHON_CMD" ]; then
    echo "✗ Python 3.12+ is required but not found."
    echo "  Install from: https://www.python.org/downloads/"
    exit 1
fi

# Check Docker (optional)
if command -v docker &>/dev/null; then
    echo "✓ Docker found (optional features available)"
else
    echo "○ Docker not found (optional — sandbox features will use local execution)"
fi

echo ""

# Create virtual environment
if [ ! -d ".venv" ]; then
    echo "→ Creating virtual environment..."
    "$PYTHON_CMD" -m venv .venv
    echo "✓ Virtual environment created"
else
    echo "✓ Virtual environment already exists"
fi

# Activate and install
echo "→ Installing dependencies..."
if [ -f ".venv/bin/pip" ]; then
    .venv/bin/pip install -q -e ".[all]"
    NEXUSAI_CMD=".venv/bin/python -m nexusai"
else
    .venv/Scripts/pip install -q -e ".[all]"
    NEXUSAI_CMD=".venv/Scripts/python -m nexusai"
fi
echo "✓ Dependencies installed"

echo ""
echo "→ Launching setup wizard..."
echo ""

# Run the interactive setup wizard
$NEXUSAI_CMD setup

echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║           Setup Complete!                     ║"
echo "║                                               ║"
echo "║  Start NexusAI:                               ║"
echo "║    make run                                   ║"
echo "║    — or —                                     ║"
echo "║    $NEXUSAI_CMD run                           ║"
echo "╚══════════════════════════════════════════════╝"
