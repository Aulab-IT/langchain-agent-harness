.PHONY: help targets install doctor test lint format typecheck client-check ci \
	handbook handbook-check handbook-html handbook-skill handbook-serve \
	sandbox-image sandbox-image-check run api client status chat smoke \
	eval calibrate improve mcp-server reset reset-all

# `make` senza argomenti mostra la guida: nessun target costoso parte per sbaglio.
.DEFAULT_GOAL := help

SANDBOX_IMAGE ?= langchain-harness-sandbox:latest
API_URL ?= http://127.0.0.1:8000
# Porta del server del manuale: diversa dall'API (8000) e dal Control Center (5173).
HANDBOOK_PORT ?= 8765

# Parametri dei target (sovrascrivibili: `make smoke GOAL="..."`).
T ?=
GOAL ?= Crea un file hello.txt con un saluto e verifica il risultato.
SINCE ?= 100
REPEAT ?= 1
ONLY ?=
YES ?=
DRY ?=

# ---------------------------------------------------------------------------------------------
# Guida
# ---------------------------------------------------------------------------------------------
# Il testo vive in una variabile esportata: attraversa la shell come un'unica stringa, quindi
# apici e accenti restano intatti anche con il Make 3.81 di macOS. I `$` vanno scritti `$$`.

define HELP_TEXT

LangChain Agent Harness — guida all'uso e alla verifica
=======================================================

Legenda:  [offline] nessun token   [docker] serve Docker attivo   [€] chiama il modello (costa)
Parametri: T=<file test>  GOAL="<obiettivo>"  SINCE=<n run>  REPEAT=<n>  ONLY=<id,id>

1. SETUP (una volta)
--------------------
  cp .env.example .env         poi inserire OPENAI_API_KEY (o ANTHROPIC_API_KEY / Ollama / MLX
                               e HARNESS_PROVIDER_LOW|MID|HIGH: un gradino, un provider)
  make install                 dipendenze Python (uv, extra dev) + client React (npm)
  make sandbox-image   [docker] costruisce l'immagine in cui gira docker_exec
  make doctor                  verifica chiave, workspace, Docker, immagine. Atteso: tutti ✓

2. USARE L'HARNESS
------------------
  make run             [docker][€] check immagine, poi API (:8000) + Control Center (:5173)
                                   apri http://127.0.0.1:5173 — Ctrl+C chiude entrambi
  make api / make client          i due processi separati, in due terminali
  make chat                  [€]  REPL CLI; ogni riga gira sullo stesso thread_id, /exit esce
  make smoke                 [€]  un run end-to-end non interattivo (GOAL=... per cambiarlo)
  make status                     con l'API attiva: backend, provider e modelli configurati
  make mcp-server                 server MCP stdio dell'harness (skill), per client esterni

3. VERIFICARE OGNI FUNZIONALITÀ
-------------------------------
test:     make test T="<file...>" con i file indicati          [offline]
dal vivo: cosa fare con `make run` per vederla funzionare davvero
Dettaglio di ogni comportamento, con l'evidenza nel codice: docs/handbook/L3/

  Config e preflight          test: tests/test_config.py tests/test_model_preflight.py
                              dal vivo: make doctor ; make status → "configured": true
  Provider e scala modelli    test: tests/test_providers.py tests/test_provider_settings.py
                              dal vivo: Impostazioni → provider; composer → fissa un gradino
  Routing ed escalation       test: tests/test_middleware.py tests/test_model_errors.py
                              dal vivo: ogni obiettivo parte dal gradino basso; se il grader
                              dà < HARNESS_ESCALATION_THRESHOLD, in Trace compare
                              l'evento model.escalated
  Loop agente e checkpoint    test: tests/test_factory.py tests/test_runner.py
                              dal vivo: make chat, due messaggi che si richiamano a vicenda
  Tool e catalogo             test: tests/test_tools.py tests/test_builtin_tools.py
                              dal vivo: tab Capabilities durante un run
  Filesystem confinato        test: tests/test_file_guard.py
                              dal vivo: chiedi di leggere ../.env → rifiutato
  Sandbox Docker + review     test: tests/test_sandbox.py tests/test_command_review.py
                              dal vivo [docker]: "esegui python -c 'print(1)'" → tab Sandbox
                              (rete off, root read-only, limiti risorse)
  Approvazione umana (HITL)   test: tests/test_interaction.py tests/test_runner.py
                              dal vivo: con HARNESS_REQUIRE_APPROVAL=true compare il modale;
                              rifiuta: l'agente riceve il rifiuto e prosegue senza eseguire
  Browser sicuro (SSRF)       test: tests/test_browser.py
                              dal vivo: chiedi di leggere http://127.0.0.1:8000 → bloccato
  Ricerca web e MCP           test: tests/test_tools.py tests/test_mcp_config.py
                              dal vivo: curl $(API_URL)/api/settings/mcp/status
  Contesto, compaction        test: tests/test_context_budget.py tests/test_context_monitor.py
                              dal vivo: Trace → finestra di contesto; compatta dalla sessione
  Budget di run               test: tests/test_run_budget.py tests/test_pricing.py
                              dal vivo: HARNESS_MAX_RUN_TOKENS basso, poi make smoke →
                              "Run fermato per budget"
  Memoria continua            test: tests/test_factory.py tests/test_server.py
                              dal vivo: memories/AGENTS.md entra nel prompt del run successivo
  Skill (progressive discl.)  test: tests/test_skills.py
                              dal vivo: vista Skills → crea/modifica, vale dal run successivo
  Planning e todo             test: tests/test_factory.py
                              dal vivo: obiettivo lungo → workspace/plan.md e lista todo
  Subagenti e routing         test: tests/test_subagents.py tests/test_subagent_routing.py
                              dal vivo: chiedi una ricerca → subagent "researcher" in Trace
  Outcome e rubrica           test: tests/test_outcome_checks.py tests/test_verification.py
                              dal vivo: fine run → voto del grader e GOAL_COMPLETE
  Esecuzione durevole         test: tests/test_durable.py
                              dal vivo: riavvia l'API con un'approvazione in sospeso →
                              curl $(API_URL)/api/durable/interrupts la mostra ancora
  Audit e trace               test: tests/test_audit.py tests/test_control_store.py
                              dal vivo: vista Traces → timeline a cascata delle tool call
  Evidence e delivery gate    test: tests/test_evidence.py tests/test_server.py
                              dal vivo: curl $(API_URL)/api/runs/<run_id>/evidence
  Trigger cron e webhook      test: tests/test_triggers.py tests/test_server.py
                              dal vivo: HARNESS_ENABLE_TRIGGERS=true, vista Triggers →
                              crea un webhook e lancia il curl che propone, cioè:
                                curl -X POST -H "X-Trigger-Token: <token>" -d '{"x":1}'
                                  "$(API_URL)/api/triggers/<id>/webhook?wait=true"
                              pagina d'esempio: demo/recensioni-webhook.html
  Self-improvement            test: tests/test_improve.py tests/test_evaluation.py
                              dal vivo [€]: make improve → vista Miglioramenti → valuta
  Canary e rollback           test: tests/test_canary.py tests/test_promotion.py
                              dal vivo: Miglioramenti → canary → promuovi → ripristina
                              una versione da curl $(API_URL)/api/config/versions
  Control plane REST/SSE      test: tests/test_server.py
                              dal vivo: make status ; curl -N .../api/sessions/<id>/events
  CLI Typer                   test: tests/test_cli.py
                              dal vivo: uv run harness --help
  Control Center React        make client-check (eslint + build TypeScript)

4. MISURARE PRIMA DI FIDARSI                                             [€][docker]
----------------------------
  make calibrate               il grader separa buone e cattive? Esce ≠0 se max(cattive)
                               >= min(buone): in quel caso l'escalation eredita rumore
  make eval REPEAT=3           eval set reale; un caso 2/3 è instabile, non passato
  make eval ONLY=id1,id2       solo alcuni casi di evals/cases.json
  make improve SINCE=100       proposta propose-only dagli ultimi N run; si valuta e
                               promuove dal Control Center

5. MANUALE DEL COMPORTAMENTO (docs/handbook/)
---------------------------------------------
  Percorso: L1_SISTEMA.md → L2_UNITA.md → L3/<unità>.md (evidenza file · righe)
  make handbook                rilocalizza le ancore, rigenera HTML e skill "manuale"
  make handbook-check          gate CI: ogni ancora è dove il manuale dice. "lost" = il
                               codice non c'è più, la pagina va riscritta
  make handbook-html           solo build/handbook/index.html, da aprire nel browser
  make handbook-serve          rigenera l'HTML e lo serve su http://127.0.0.1:$(HANDBOOK_PORT)
                               (HANDBOOK_PORT=... per cambiarla, Ctrl+C per fermarlo)

6. PRIMA DI UN COMMIT                                                      [offline]
---------------------
  make ci                      lint + typecheck + handbook-check + test + client-check:
                               gli stessi controlli della CI GitHub, in locale
  make format                  ruff format + fix automatico

7. RIPARTIRE DA ZERO                                             (API spenta)
--------------------
  make reset DRY=1             elenca cosa verrebbe cancellato, senza toccare niente
  make reset                   cancella i dati delle sessioni: sessioni, messaggi, run,
                               trace, checkpoint, interrupt, audit, workspace, eval,
                               self-improvement, container e reti sandbox; riporta
                               memories/AGENTS.md alla versione in git
  make reset-all               in più: provider e parametri runtime, server MCP, rubric,
                               skill installate, subagenti modificati dal Control Center
  Restano sempre: .env, codice, output/, immagine sandbox. Chiede di scrivere "reset";
  YES=1 salta la conferma.

Documenti: README.md · docs/GUIDA_DIDATTICA_COMPLETA.md · docs/HARNESS_COMPONENTS.md
           docs/MATRICE_COPERTURA_DIDATTICA.md · docs/SELF_IMPROVEMENT.md · SECURITY.md
Elenco compatto dei target: make targets

endef
export HELP_TEXT

# Colora la guida riga per riga. Il colore si accende solo se l'uscita è un terminale e
# NO_COLOR non è impostata: `make help > guida.txt` resta testo pulito.
define HELP_AWK
BEGIN {
	e = sprintf("%c", 27)
	if (color) {
		R = e "[0m"; B = e "[1m"; D = e "[2m"
		TITLE = e "[1;36m"; SEC = e "[1;33m"; CMD = e "[32m"
		TEST = e "[36m"; LIVE = e "[35m"; COST = e "[1;31m"; DOCK = e "[34m"; OFF = e "[32m"
	}
}
function paint(s) {
	gsub(/make [a-z][a-z-]*/, CMD "&" R, s)
	gsub(/test:/, TEST "&" R, s)
	gsub(/dal vivo:/, LIVE "&" R, s)
	gsub(/\[€\]/, COST "&" R, s)
	gsub(/\[docker\]/, DOCK "&" R, s)
	gsub(/\[offline\]/, OFF "&" R, s)
	gsub(/^(Legenda|Parametri|Documenti|Dettaglio di ogni comportamento[^:]*):/, B "&" R, s)
	return s
}
/guida all'uso e alla verifica/ { print TITLE $$0 R; next }
/^[0-9]\. / { section = substr($$0, 1, 1); print SEC $$0 R; next }
/^(=+|-+)$$/ { print D $$0 R; next }
# Solo nella sezione 3 una riga che inizia con una maiuscola è il nome di una funzionalità.
section == 3 && /^  [A-Z]/ { print B substr($$0, 1, 30) R paint(substr($$0, 31)); next }
{ print paint($$0) }
endef
export HELP_AWK

# Vero se lo standard output del recipe è un terminale a colori.
USE_COLOR = if [ -t 1 ] && [ -z "$$NO_COLOR" ]; then c=1; else c=0; fi

help: ## Guida completa all'uso e alla verifica (target predefinito)
	@$(USE_COLOR); printf '%s\n' "$$HELP_TEXT" | awk -v color=$$c "$$HELP_AWK"

targets: ## Elenco compatto dei target con la loro descrizione
	@$(USE_COLOR); grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) \
		| awk -v color=$$c 'BEGIN {FS = ":.*## "; if (color) {g = sprintf("%c[32m", 27); r = sprintf("%c[0m", 27)}} \
			{printf "  %s%-20s%s %s\n", g, $$1, r, $$2}'

# ---------------------------------------------------------------------------------------------
# Setup e qualità
# ---------------------------------------------------------------------------------------------

install: ## Dipendenze Python (extra dev) e client React
	uv sync --extra dev
	cd client && npm install

doctor: ## Prerequisiti: chiave, workspace, Docker, immagine sandbox (nessun token)
	uv run harness doctor

test: ## Test offline (T=tests/test_x.py per un sottoinsieme)
	uv run pytest $(T)

lint: ## Ruff su src, tests, evals, scripts
	uv run ruff check src tests evals scripts

format: ## Ruff format + fix automatico
	uv run ruff format src tests evals scripts
	uv run ruff check --fix src tests evals scripts

typecheck: ## Mypy strict su agent_harness (come in CI)
	uv run mypy src/agent_harness

client-check: ## Lint e build del Control Center (come in CI)
	cd client && npm run lint && npm run build

ci: lint typecheck handbook-check test client-check ## Tutti i controlli offline della CI

# ---------------------------------------------------------------------------------------------
# Manuale
# ---------------------------------------------------------------------------------------------

handbook: ## Rilocalizza le ancore e rigenera HTML e skill del manuale
	uv run python scripts/handbook_sync.py --write
	uv run python scripts/handbook_html.py
	uv run python scripts/handbook_skill.py

handbook-check: ## Gate CI: ogni ancora del manuale punta al codice giusto
	uv run python scripts/handbook_sync.py --vendor-check
	uv run python scripts/handbook_sync.py --check
	uv run python scripts/handbook_skill.py --check

handbook-html: ## Solo l'artefatto navigabile in build/handbook/
	uv run python scripts/handbook_html.py

handbook-skill: ## Solo la skill "manuale" generata dal manuale
	uv run python scripts/handbook_skill.py

handbook-serve: handbook-html ## Serve il manuale su http://127.0.0.1:HANDBOOK_PORT (8765)
	@lsof -nP -iTCP:$(HANDBOOK_PORT) -sTCP:LISTEN >/dev/null 2>&1 && { \
		echo "La porta $(HANDBOOK_PORT) è già occupata. Usa: make handbook-serve HANDBOOK_PORT=<altra>"; \
		exit 1; \
	} || true
	@echo "Manuale su http://127.0.0.1:$(HANDBOOK_PORT)  (Ctrl+C per fermare)"
	@uv run python -m http.server $(HANDBOOK_PORT) --bind 127.0.0.1 --directory build/handbook

# ---------------------------------------------------------------------------------------------
# Sandbox ed esecuzione
# ---------------------------------------------------------------------------------------------

sandbox-image: ## Costruisce l'immagine Docker della sandbox
	docker build -t $(SANDBOX_IMAGE) -f docker/sandbox.Dockerfile docker/

sandbox-image-check: ## Verifica Docker attivo e immagine sandbox presente
	@docker version >/dev/null 2>&1 || { \
		echo "Docker non è attivo. Avvia Docker Desktop, Colima o OrbStack (docker context show), poi riprova."; \
		exit 1; \
	}
	@docker image inspect $(SANDBOX_IMAGE) >/dev/null 2>&1 || { \
		echo "Immagine sandbox $(SANDBOX_IMAGE) assente."; \
		echo "Costruiscila una volta con: make sandbox-image"; \
		exit 1; \
	}

run: sandbox-image-check ## API + Control Center insieme (http://127.0.0.1:5173)
	@trap 'kill 0' INT TERM EXIT; \
	uv run harness-api & \
	cd client && npm run dev & \
	wait

api: ## Solo il control plane FastAPI su :8000
	uv run harness-api

client: ## Solo il Control Center (Vite) su :5173
	cd client && npm run dev

status: ## Stato runtime dell'API in esecuzione (/api/status)
	@curl -fsS $(API_URL)/api/status | uv run python -m json.tool || { \
		echo "API non raggiungibile su $(API_URL). Avviala con: make api"; \
		exit 1; \
	}

chat: ## Chat interattiva CLI (costa token)
	uv run harness chat

smoke: ## Run end-to-end di verifica (GOAL="..." per cambiarlo; costa token)
	uv run harness run "$(GOAL)"

mcp-server: ## Server MCP stdio dell'harness (skill) per client esterni
	uv run python -m agent_harness.mcp_server

# ---------------------------------------------------------------------------------------------
# Valutazione e self-improvement (costano token)
# ---------------------------------------------------------------------------------------------

eval: ## Eval set reale (REPEAT=n, ONLY=id1,id2)
	uv run harness eval --repeat $(REPEAT) $(if $(ONLY),--only $(ONLY))

calibrate: ## Il grader separa le risposte buone dalle cattive? (REPEAT=n)
	uv run python evals/calibrate_grader.py --repeat $(REPEAT)

improve: ## Proposta di miglioramento dagli ultimi SINCE run (propose-only)
	uv run harness improve --since $(SINCE)

# ---------------------------------------------------------------------------------------------
# Ripartire da zero
# ---------------------------------------------------------------------------------------------

RESET_FLAGS = $(if $(YES),--yes) $(if $(DRY),--dry-run)

reset: ## Cancella i dati delle sessioni (DRY=1 per vedere, YES=1 senza conferma)
	@scripts/reset_state.sh $(RESET_FLAGS)

reset-all: ## Come reset, più la configurazione fatta dal Control Center
	@scripts/reset_state.sh --all $(RESET_FLAGS)
