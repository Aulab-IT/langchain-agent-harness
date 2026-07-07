# Mappa dei componenti dell'harness

L'articolo definisce l'harness come tutto ciò che circonda il modello e rende la sua
intelligenza utilizzabile. Questa tabella collega ogni comportamento desiderato al
meccanismo concreto presente nel progetto.

| Componente | Implementazione | Step |
|---|---|---|
| Prompt di sistema | `prompts.py`, memoria sempre caricata | 01, 08 |
| Loop modello | LangChain `create_agent` e runtime LangGraph | 01 |
| Tool calling / ReAct | tool tipizzati e ciclo azione-osservazione | 02 |
| Stato durevole | checkpoint SQLite e `thread_id` | 03 |
| Filesystem | backend confinato in `workspace` | 04 |
| Bash e codice | `docker_exec` in container effimero | 05 |
| Ambiente isolato | rete/capability rimosse, limiti di risorse | 05 |
| Browser / pagine | lettura HTML con difese SSRF e limite dimensione | 06 |
| Conoscenza recente | ricerca web opzionale | 06 |
| MCP | server locale e adapter multi-server | 06 |
| Compaction | middleware di summarization di Deep Agents | 07 |
| Tool-output offloading | filesystem middleware di Deep Agents | 07 |
| Memoria continua | `memories/AGENTS.md` persistente | 08 |
| Skills | `SKILL.md` caricati con progressive disclosure | 08 |
| Pianificazione | todo middleware e `workspace/plan.md` | 09 |
| Auto-verifica | tool `verify_workspace` e hook del runner | 09 |
| Subagenti | ricercatore e revisore con contesto isolato | 10 |
| Model routing | middleware che sceglie modello economico o forte | 10 |
| Human-in-the-loop | interrupt prima dei tool sensibili | 11 |
| Limiti deterministici | tool-call limit, timeout, continuation budget | 11 |
| Ralph-style continuation | reiniezione obiettivo in contesto nuovo e limitato | 11 |
| Osservabilità | stream eventi e tracing LangSmith opzionale | 12 |
| Audit hook | middleware JSONL senza argomenti o segreti | 11, 12 |

## Confini intenzionali

L'articolo descrive una famiglia di scelte architetturali, non un'unica API. Il progetto
usa Deep Agents perché è l'implementazione LangChain orientata agli harness, ma mantiene
visibili i singoli meccanismi attraverso gli step.

La continuazione non è infinita: il runner usa un budget configurabile. Un agente deve
scrivere il marcatore `[GOAL_COMPLETE]` solo dopo una verifica; altrimenti riceve nuovamente
l'obiettivo e lo stato del lavoro. Questo conserva l'idea del Ralph loop senza creare un
processo incontrollabile.

L'interrupt di approvazione è unico per turno ma può contenere più tool call sensibili
chiamati in parallelo (`action_requests`): il runner deve rispondere con altrettante
decisioni, non con una sola, altrimenti `HumanInTheLoopMiddleware` va in errore e il run
fallisce. `GoalRunner._invoke_with_approval` replica la decisione dell'utente su tutte le
`action_requests` in sospeso, così la UI resta a singola conferma per turno.

## Loop engineering (quattro loop impilati)

Oltre all'anatomia dell'harness, il progetto implementa i quattro loop descritti in
[*The Art of Loop Engineering*](https://www.langchain.com/blog/the-art-of-loop-engineering).

| Loop | Cosa fa | Implementazione |
|---|---|---|
| 1 · Agent loop | modello + tool in ciclo | `create_deep_agent` in `factory.py` |
| 2 · Verification loop | grader a rubric che valuta l'output e reinietta feedback | `verification.py` (`RubricGrader`) + integrazione nel continuation di `runner.py`; eventi `grader.*` nella trace |
| 3 · Event-driven loop | cron e webhook avviano run autonomi | `triggers.py` (`TriggerScheduler`, `cron_matches`), tabella `triggers`, endpoint `/api/triggers` in `server.py` |
| 4 · Hill-climbing loop | trace propongono modifiche, eval gate confronta baseline/candidato, canary live verifica non inferiorità | `improve.py`, `evaluation.py`, `canary.py`, `promotion.py`; override letti dalla `factory.py` |

Il Loop 2 usa lo stesso budget di continuation Ralph-style invece di un nuovo grafo; l'articolo
cita anche `RubricMiddleware`/hook `after_agent` come alternativa nativa LangChain. Il Loop 4
non modifica mai il codice: scrive proposte in `state/improvements/`, esegue baseline e
candidato sull'eval set versionato, poi abilita canary o promotion solo se il gate passa.
Gli override ammessi sono `system_prompt_addendum` e `harness_max_tool_calls`; rubric e soglia
restano congelate per impedire reward hacking.
La finestra usa un numero di run, non un numero di eventi: delta streaming e audit storici
non falsano più statistiche, error rate o feedback analizzati.
