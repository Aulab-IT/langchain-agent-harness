# Matrice di copertura didattica

Questa matrice è criterio di completezza del percorso. Ogni famiglia di funzionalità del sistema
finale deve avere almeno una spiegazione, uno snapshot eseguibile e una prova automatica. I notebook
sono micro-laboratori autonomi; gli step mostrano integrazione incrementale; `src/agent_harness`
resta implementazione completa.

| Funzionalità | Implementazione finale | Step | Notebook | Verifica principale |
|---|---|---:|---:|---|
| Config tipizzata e preflight | `config.py`, `model_preflight.py` | 00, 14 | 07 | `test_config.py`, `test_model_preflight.py` |
| Chiamata modello e loop agente | `factory.py`, LangGraph | 01–02 | 01 | `test_factory.py`, `test_runner.py` |
| Tool calling e catalogo | `tools.py`, `builtin_tools.py` | 02 | 01–02 | `test_tools.py`, `test_builtin_tools.py` |
| Checkpoint e thread | `factory.py`, SQLite saver | 03 | 03 | `test_factory.py`, `test_server.py` |
| Filesystem confinato | `file_guard.py`, backend Deep Agents | 04 | 02 | `test_file_guard.py` |
| Sandbox e command review | `sandbox.py`, `command_review.py` | 05 | 02, 05 | `test_sandbox.py`, `test_command_review.py` |
| Browser sicuro / SSRF | `browser.py` | 06 | 02 | `test_browser.py` |
| Ricerca web e MCP | `tools.py`, `mcp_config.py`, `mcp_server.py` | 06 | 06 | `test_mcp_config.py`, `test_tools.py` |
| Compaction e offload | `context_budget.py`, `context_monitor.py` | 07, 15 | 03, 08 | `test_context_budget.py`, `test_context_monitor.py` |
| Memoria continua | `prompts.py`, memory file | 08 | 03 | `test_factory.py`, `test_server.py` |
| Skill progressive disclosure | `skills.py`, `builtin_tools.py` | 08 | 05 | `test_skills.py` |
| Planning e todo | Deep Agents middleware, `prompts.py` | 09 | 04 | `test_factory.py` |
| Outcome e verifica a rubrica | `outcome_checks.py`, `verification.py` | 09, 13 | 05–06 | `test_outcome_checks.py`, `test_verification.py` |
| Subagenti isolati | `subagents.py` | 10 | 04 | `test_subagents.py` |
| Routing e governance subagenti | `subagent_routing.py` | 17 | 10 | `test_subagent_routing.py` |
| Human-in-the-loop | `runner.py`, `interaction.py` | 11, 16 | 05, 09 | `test_interaction.py`, `test_runner.py` |
| Continuation e stati terminali | `runner.py`, `durable.py` | 11, 16 | 06, 09 | `test_runner.py`, `test_durable.py` |
| Provider multipli e capability | `providers.py`, `provider_settings.py` | 14 | 07 | `test_providers.py`, `test_provider_settings.py` |
| Routing modelli e tassonomia errori | `middleware.py`, `model_errors.py` | 10, 14 | 04, 07 | `test_middleware.py`, `test_model_errors.py` |
| Pricing e usage | `pricing.py`, `usage.py` | 14–15 | 07–08 | `test_pricing.py`, `test_run_budget.py` |
| Budget contesto e run | `context_budget.py`, `run_budget.py` | 15 | 08 | `test_context_budget.py`, `test_run_budget.py` |
| Esecuzione durevole | `durable.py` | 16 | 09 | `test_durable.py` |
| Audit e trace | `audit.py`, `control_store.py` | 12, 19 | 05 | `test_audit.py`, `test_control_store.py` |
| Trigger cron/webhook | `triggers.py`, `server.py` | 13, 19 | 06 | `test_triggers.py`, `test_server.py` |
| Self-improvement propose-only | `improve.py` | 13 | 06 | `test_improve.py` |
| Eval e regression gate | `evaluation.py` | 13 | 12 | `test_evaluation.py` |
| Canary, promotion, rollback | `canary.py`, `promotion.py` | 13 | 12 | `test_canary.py`, `test_promotion.py` |
| Manifest e checker indipendente | `evidence.py` | 18 | 11 | `test_evidence.py` |
| Delivery gate | `evidence.py`, `server.py` | 18–19 | 11 | `test_evidence.py`, `test_server.py` |
| Control plane REST/SSE | `server.py`, `control_store.py` | 19 | — | `test_server.py`, `test_control_store.py` |
| CLI Typer | `cli.py`, `runner.py` | 12, 19 | — | `test_cli.py` |
| Control Center React | `client/src` | 19 | — | lint e build frontend |

## Perché alcuni temi non sono in un notebook

UI React, processo API, Docker e provider reali dipendono da runtime esterni. Riprodurli interamente
in un notebook ne distruggerebbe granularità e autonomia. Il percorso usa quindi tre livelli:

1. notebook per algoritmo o meccanismo isolato;
2. step per integrazione eseguibile;
3. applicazione finale per comportamento end-to-end.

## Controlli di completezza

```bash
make notebooks   # compila 01-12 ed esegue offline 07-12
make test        # include struttura, guide e changelog di ogni step
make lint        # codice mantenuto dal progetto, esclusi sorgenti skill vendorizzati
cd client && npm run lint && npm run build
```
