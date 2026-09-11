.PHONY: install test lint format handbook handbook-check handbook-html handbook-skill sandbox-image sandbox-image-check run chat smoke

SANDBOX_IMAGE ?= langchain-harness-sandbox:latest

install:
	uv sync --extra dev
	cd client && npm install

test:
	uv run pytest

lint:
	uv run ruff check src tests evals scripts

format:
	uv run ruff format src tests evals scripts
	uv run ruff check --fix src tests evals scripts

handbook:
	uv run python scripts/handbook_sync.py --write
	uv run python scripts/handbook_html.py
	uv run python scripts/handbook_skill.py

handbook-check:
	uv run python scripts/handbook_sync.py --vendor-check
	uv run python scripts/handbook_sync.py --check
	uv run python scripts/handbook_skill.py --check

handbook-html:
	uv run python scripts/handbook_html.py

handbook-skill:
	uv run python scripts/handbook_skill.py

sandbox-image:
	docker build -t $(SANDBOX_IMAGE) -f docker/sandbox.Dockerfile docker/

sandbox-image-check:
	@docker version >/dev/null 2>&1 || { \
		echo "Docker non è attivo. Avvia Docker Desktop, poi riprova."; \
		exit 1; \
	}
	@docker image inspect $(SANDBOX_IMAGE) >/dev/null 2>&1 || { \
		echo "Immagine sandbox $(SANDBOX_IMAGE) assente."; \
		echo "Costruiscila una volta con: make sandbox-image"; \
		exit 1; \
	}

run: sandbox-image-check
	@trap 'kill 0' INT TERM EXIT; \
	uv run harness-api & \
	cd client && npm run dev & \
	wait

chat:
	uv run harness chat

smoke:
	uv run harness run "Crea un file hello.txt con un saluto e verifica il risultato."
