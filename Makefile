.PHONY: install test lint format notebooks notebooks-live sandbox-image run chat smoke

install:
	uv sync --extra dev
	cd client && npm install

test:
	uv run pytest

lint:
	uv run ruff check src tests evals scripts steps

format:
	uv run ruff format src tests evals scripts steps
	uv run ruff check --fix src tests evals scripts steps

notebooks:
	uv run python scripts/validate_notebooks.py --execute-offline

notebooks-live:
	uv run python scripts/validate_notebooks.py --execute

sandbox-image:
	docker build -t langchain-harness-sandbox:latest -f docker/sandbox.Dockerfile .

run:
	@trap 'kill 0' INT TERM EXIT; \
	uv run harness-api & \
	cd client && npm run dev & \
	wait

chat:
	uv run harness chat

smoke:
	uv run harness run "Crea un file hello.txt con un saluto e verifica il risultato."
