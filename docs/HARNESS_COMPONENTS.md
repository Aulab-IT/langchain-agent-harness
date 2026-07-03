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
