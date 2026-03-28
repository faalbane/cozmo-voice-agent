#!/usr/bin/env bash
# Run progressive load test against the voice agent system.
# Requires the full stack to be running (docker compose up).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "============================================"
echo "  Voice Agent Load Test Suite"
echo "============================================"
echo ""
echo "Prerequisites:"
echo "  - docker compose up (all services running)"
echo "  - Knowledge base seeded"
echo ""

# Check if stack is running
if ! curl -sf http://localhost:7880 > /dev/null 2>&1; then
  echo "ERROR: LiveKit server not reachable at localhost:7880"
  echo "Run: docker compose up -d"
  exit 1
fi

echo "Stack is running. Starting load tests..."
echo ""

cd "$PROJECT_DIR"
python -m tests.load.load_test

echo ""
echo "============================================"
echo "  Load test complete!"
echo "  Results: tests/load/results/load_test_report.json"
echo "  Grafana: http://localhost:3000"
echo "============================================"
