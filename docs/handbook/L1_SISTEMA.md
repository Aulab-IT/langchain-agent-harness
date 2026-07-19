# L1 · Sistema

Come gira l'harness nel suo insieme: da dove entra una richiesta, quali stadi attraversa,
come si muove lo stato tra uno stadio e l'altro, e come l'output del modello diventa
un'azione reale.

## Due superfici di ingresso, un solo motore

```
CLI (harness chat / run)        Control Plane (FastAPI + SSE)
        │                                │
        │  ask_approval() da terminale   │  approval() da REST + modale React
        └──────────────┬─────────────────┘
                       ▼
                  GoalRunner
                       │
                       ▼
              LangGraph / Deep Agent
```

Le due superfici differiscono **solo per i callback** che passano al `GoalRunner`:
approvazione, azione utente, eventi. Il ciclo di vita del run è identico. È il motivo per
cui una regola di sicurezza scritta nel grafo vale automaticamente su entrambe: non esiste
un percorso «CLI» che salti i controlli del percorso «web».

- CLI: `cli.py · L77–83` costruisce `GoalRunner(harness, ask_approval)`.
- Control plane: `server.py · L1322` costruisce `GoalRunner(harness, approval, agent_event, interaction)`.

## Gli stadi

### 1 · Configurazione e composizione

`config.py` valida l'input di configurazione (`Settings`); `factory.py` compone il grafo.
La composizione è il punto in cui vengono decise, una volta per run, le policy che poi
valgono per tutta la sua durata: quali tool esistono, quali richiedono approvazione, quale
ladder di modelli è disponibile, quale radice di filesystem è scrivibile.

`build_harness` è un async context manager: apre il checkpointer SQLite, costruisce il
grafo, lo cede, e garantisce il rilascio (`factory.py · L1031–1050`).

**Invariante:** `factory.py` compone, non decide a runtime. Le decisioni per-chiamata
stanno nelle `when` callable e nei middleware, non nel corpo della factory.

### 2 · Assemblaggio del contesto

Prima di ogni turno l'harness prepara ciò che il modello vedrà: system prompt (`prompts.py`),
memoria continua sempre caricata (`memories/AGENTS.md`), skill disponibili per titolo e
caricate per intero solo su richiesta, todo di pianificazione, e la storia conversazionale
potata per stare nella finestra (`context_budget.py`, `context_monitor.py`).

### 3 · Esecuzione del turno

Il grafo Deep Agent chiama il modello, stream dei delta, raccoglie le tool call. Il router
(`middleware.py`) sceglie il gradino della ladder chiamata per chiamata: il modello passato
a `create_deep_agent` è solo il punto di partenza, ed è il più economico (`factory.py · L1032–1035`).

Lo streaming passa da `GoalRunner._invoke_graph` (`runner.py · L129–155`), che emette
`assistant.delta` e snapshot di usage mentre il grafo avanza.

Prima di ogni chiamata i blocchi-file allegati vengono ispezionati, perché un allegato
malformato renderebbe la conversazione irrecuperabile.
→ [3.1](L2_UNITA.md#31--igiene-dei-blocchi-file-verso-il-provider)

### 4 · Esecuzione degli effetti collaterali — **lo stadio guardato**

Quando il modello chiede di fare qualcosa che esce dal testo, il turno **non prosegue
dritto**. Si interpone il livello guardato: policy di approvazione, sospensione del run,
raccolta della decisione umana, e solo dopo l'esecuzione vera in sandbox.

È lo stadio con la maggiore densità di comportamento e il maggior numero di siti di
implementazione. → [L2](L2_UNITA.md#stadio-4--esecuzione-guardata-degli-effetti-collaterali)

### 5 · Continuazione e verifica

Il run non finisce quando il modello smette di parlare. `GoalRunner` reinietta l'obiettivo
finché non compare il marcatore `[GOAL_COMPLETE]` **e** la verifica è passata, entro un
budget di continuazione configurabile (`runner.py · L200–334`). Un grader a rubric valuta
l'output e reinietta feedback (`verification.py`).

### 6 · Persistenza e proiezione

Messaggi e stato del grafo vivono nei checkpoint SQLite; run, trace, usage ed eventi vivono
in `state/control.sqlite` (`control_store.py`); gli artefatti vivono nel workspace isolato
per thread. Il client riceve tutto via SSE.

### 7 · Chiusura

Alla fine del run il control plane chiude gli interrupt durevoli rimasti pendenti e
rilascia le future di approvazione (`server.py · L1676–1691`). Un run terminato non deve
lasciare interrupt orfani in SQLite.

## Strati trasversali

| Strato | Dove | Note |
|---|---|---|
| Lavoro durevole | `durable.py` | state machine dei run, coda con lease, interrupt persistiti |
| Osservabilità | `audit.py`, `control_store.py` | JSONL senza argomenti né segreti + trace per run |
| Budget | `run_budget.py`, `context_budget.py` | prenotazioni concorrenti su token/costo/call/tempo |
| Astrazione provider | `providers.py`, `pricing.py`, `model_errors.py` | registry, capability, costo normalizzato |
| Evidenza | `evidence.py` | manifest hashati, checker su snapshot read-only |

## Dove NON c'è uno stadio

Utile quanto sapere dove c'è, se stai verificando o adattando:

- **Nessuno stadio di autenticazione.** Solo `OPENAI_API_KEY` da ambiente. Non esistono
  login flow, token storage, né adattamento credenziali per provider.
- **Nessun motore di patch.** L'agente scrive file interi tramite il filesystem backend;
  non applica diff strutturati con validazione di formato.
- **Nessuna review secondaria (guardian).** Ciò che viene auto-approvato non viene
  ricontrollato da un secondo giudice.
- **Nessun hook di lifecycle configurabile.** Le regole di approvazione sono nel codice di
  `factory.py`, non estendibili dall'esterno senza modificarlo.
