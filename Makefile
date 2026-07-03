.PHONY: install test lint format notebooks notebooks-live sandbox-image run smoke

install:
	uv sync --extra dev

test:
	uv run pytest

lint:
	uv run ruff check .

format:
	uv run ruff format .
	uv run ruff check --fix .

notebooks:
	uv run python scripts/validate_notebooks.py

notebooks-live:
	uv run python scripts/validate_notebooks.py --execute

sandbox-image:
	docker build -t langchain-harness-sandbox:latest -f docker/sandbox.Dockerfile .

run:
	uv run harness chat

smoke:
	uv run harness run "Crea un file hello.txt con un saluto e verifica il risultato."
