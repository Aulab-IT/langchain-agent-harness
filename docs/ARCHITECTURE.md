# Architettura

```text
CLI
 └─ GoalRunner
     ├─ approvazione interrupt
     ├─ budget di continuazione
     └─ LangGraph / Deep Agent
         ├─ modello OpenAI + router
         ├─ planning e compaction
         ├─ filesystem + memoria + skills
         ├─ tool locali, web e MCP
         ├─ subagenti isolati
         ├─ audit e limiti
         └─ checkpoint SQLite
```

## Ciclo di vita

`build_harness` apre il checkpointer SQLite, costruisce il graph e lo rilascia tramite
async context manager. Un `thread_id` stabile collega le invocazioni. Gli artefatti vivono
nel filesystem, mentre messaggi e stato del graph vivono nei checkpoint.

## Separazione delle responsabilità

- `config.py`: input di configurazione validato.
- `factory.py`: composizione, non logica applicativa.
- `runner.py`: obiettivo, interrupt e continuazione.
- `sandbox.py`: confine di esecuzione.
- `browser.py`: confine di rete per lettura pagine.
- `tools.py`: registrazione dei tool.
- `middleware.py`: scelta del modello.
- `audit.py`: osservabilità senza contenuti sensibili.
- `mcp_server.py`: esempio di integrazione fuori processo.

