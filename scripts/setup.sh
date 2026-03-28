#!/usr/bin/env bash
# One-command setup for the Voice Agent system.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "============================================"
echo "  ShopEase Voice Agent - Setup"
echo "============================================"
echo ""

cd "$PROJECT_DIR"

# 1. Check for .env
if [ ! -f .env ]; then
  echo "Creating .env from .env.example..."
  cp .env.example .env
  echo "IMPORTANT: Edit .env with your API keys before starting."
  echo ""
fi

# 2. Install Python dependencies
echo "Installing Python dependencies..."
pip install -e ".[dev]" --quiet

# 3. Start infrastructure
echo "Starting infrastructure (Redis, ChromaDB, Prometheus, Grafana)..."
docker compose up -d redis chromadb prometheus grafana

echo "Waiting for services to be ready..."
sleep 5

# 4. Seed knowledge base
echo "Seeding knowledge base..."
python scripts/seed_knowledge.py

echo ""
echo "============================================"
echo "  Setup complete!"
echo ""
echo "  Next steps:"
echo "    1. Edit .env with your API keys"
echo "    2. Start the agent:  python src/main.py dev"
echo "    3. Start dashboard:  make dashboard"
echo "    4. View Grafana:     http://localhost:3000"
echo "============================================"
