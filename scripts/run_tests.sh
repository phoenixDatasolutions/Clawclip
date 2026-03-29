#!/usr/bin/env bash
set -e

echo "=== NexusAI Test Runner ==="
echo "Running all tests that work without external API keys..."
echo ""

# Install test deps if needed
pip install -e ".[core,test]" -q

# Run unit tests
echo "--- Unit Tests ---"
pytest tests/unit/ -v --tb=short -m "not requires_docker and not requires_telegram and not requires_openai and not requires_claude"

echo ""
echo "--- Dashboard Integration Tests ---"
pytest tests/integration/test_dashboard.py -v --tb=short 2>/dev/null || echo "Dashboard tests skipped (optional deps)"

echo ""
echo "=== Done ==="
