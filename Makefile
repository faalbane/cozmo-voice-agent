.PHONY: setup dev test load-test lint clean

setup:
	pip install -e ".[dev]"
	python scripts/seed_knowledge.py

dev:
	docker compose up -d redis chromadb prometheus grafana
	python src/main.py dev

up:
	docker compose up -d

down:
	docker compose down

test:
	pytest tests/ -v --cov=src

load-test:
	bash scripts/run_load_test.sh

lint:
	ruff check src/ tests/
	ruff format --check src/ tests/

format:
	ruff check --fix src/ tests/
	ruff format src/ tests/

seed-kb:
	python scripts/seed_knowledge.py

dashboard:
	python -m uvicorn src.dashboard:app --host 0.0.0.0 --port 8080

clean:
	docker compose down -v
	find . -type d -name __pycache__ -exec rm -rf {} +
	rm -rf .pytest_cache .ruff_cache
