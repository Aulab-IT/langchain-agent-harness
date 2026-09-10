# Matrice di copertura didattica

Questa matrice è criterio di completezza: ogni famiglia di funzionalità del sistema deve avere
un'implementazione e almeno una prova automatica che la esercita. Serve a rispondere a una domanda
sola — «questa cosa, chi la implementa e cosa la verifica?» — e a rendere visibile un buco quando
si apre.

Per il *comportamento* — cosa succede quando l'agente prova a fare qualcosa, con l'evidenza
`file · riga` di ogni affermazione — il riferimento è il manuale in
[`handbook/`](handbook/README.md), organizzato per unità di comportamento invece che per modulo.

| Funzionalità | Implementazione finale | Verifica principale |
|---|---|---|
| Config tipizzata e preflight | `config.py`, `model_preflight.py` | `test_config.py`, `test_model_preflight.py` |
| Chiamata modello e loop agente | `factory.py`, LangGraph | `test_factory.py`, `test_runner.py` |
| Tool calling e catalogo | `tools.py`, `builtin_tools.py` | `test_tools.py`, `test_builtin_tools.py` |
| Checkpoint e thread | `factory.py`, SQLite saver | `test_factory.py`, `test_server.py` |
| Filesystem confinato | `file_guard.py`, backend Deep Agents | `test_file_guard.py` |
| Sandbox e command review | `sandbox.py`, `command_review.py` | `test_sandbox.py`, `test_command_review.py` |
| Browser sicuro / SSRF | `browser.py` | `test_browser.py` |
| Ricerca web e MCP | `tools.py`, `mcp_config.py`, `mcp_server.py` | `test_mcp_config.py`, `test_tools.py` |
| Compaction e offload | `context_budget.py`, `context_monitor.py` | `test_context_budget.py`, `test_context_monitor.py` |
| Memoria continua | `prompts.py`, memory file | `test_factory.py`, `test_server.py` |
| Skill progressive disclosure | `skills.py`, `builtin_tools.py` | `test_skills.py` |
| Planning e todo | Deep Agents middleware, `prompts.py` | `test_factory.py` |
| Outcome e verifica a rubrica | `outcome_checks.py`, `verification.py` | `test_outcome_checks.py`, `test_verification.py` |
| Subagenti isolati | `subagents.py` | `test_subagents.py` |
| Routing e governance subagenti | `subagent_routing.py` | `test_subagent_routing.py` |
| Human-in-the-loop | `runner.py`, `interaction.py` | `test_interaction.py`, `test_runner.py` |
| Continuation e stati terminali | `runner.py`, `durable.py` | `test_runner.py`, `test_durable.py` |
| Provider multipli e capability | `providers.py`, `provider_settings.py` | `test_providers.py`, `test_provider_settings.py` |
| Routing modelli e tassonomia errori | `middleware.py`, `model_errors.py` | `test_middleware.py`, `test_model_errors.py` |
| Pricing e usage | `pricing.py`, `usage.py` | `test_pricing.py`, `test_run_budget.py` |
| Budget contesto e run | `context_budget.py`, `run_budget.py` | `test_context_budget.py`, `test_run_budget.py` |
| Esecuzione durevole | `durable.py` | `test_durable.py` |
| Audit e trace | `audit.py`, `control_store.py` | `test_audit.py`, `test_control_store.py` |
| Trigger cron/webhook | `triggers.py`, `server.py` | `test_triggers.py`, `test_server.py` |
| Self-improvement propose-only | `improve.py` | `test_improve.py` |
| Eval e regression gate | `evaluation.py` | `test_evaluation.py` |
| Canary, promotion, rollback | `canary.py`, `promotion.py` | `test_canary.py`, `test_promotion.py` |
| Manifest e checker indipendente | `evidence.py` | `test_evidence.py` |
| Delivery gate | `evidence.py`, `server.py` | `test_evidence.py`, `test_server.py` |
| Control plane REST/SSE | `server.py`, `control_store.py` | `test_server.py`, `test_control_store.py` |
| CLI Typer | `cli.py`, `runner.py` | `test_cli.py` |
| Control Center React | `client/src` | lint e build frontend |

## Cosa non compare qui

Le skill non sono una riga della matrice perché non sono codice del progetto: vivono in
`.agents/skills/` come dati dell'utente, ognuno installa le proprie e il repository non le
versiona. Il meccanismo che le espone al modello, invece, sì — è `skills.py` più la riga di
`factory.py` che passa al grafo il *percorso* e non il contenuto.

## Controlli di completezza

```bash
make test            # test offline, senza consumo di token
make lint            # analisi statica del codice mantenuto dal progetto
make handbook-check  # ogni riferimento del manuale punta ancora al codice giusto
cd client && npm run lint && npm run build
```
