# L2 · Unità di comportamento

Ogni unità è un pezzo coerente di comportamento: ha una responsabilità, ingressi e uscite,
dipendenze e stato proprio. Le unità sono raggruppate per stadio L1, e ognuna ha un
dettaglio L3 con l'evidenza nel codice.

---

## Stadio 1 · Configurazione e composizione

### 1.1 · Confinamento del filesystem

> **Responsabilità.** Garantire che ogni lettura e scrittura resti dentro la radice della
> sessione, indipendentemente dal path richiesto dal modello.

Non è un gate che chiede permesso: è un confine che nega. Tre difese sovrapposte — radice
virtuale del backend, allow-list con deny finale, isolamento per sessione — più permessi
read-only per i subagenti.

| | |
|---|---|
| **Ingressi** | operazioni su file richieste dal modello |
| **Uscite** | operazione eseguita, o errore di permesso al modello |
| **Stato** | nessuno — è una policy, non un processo |
| **Siti** | `factory.py`, `config.py`, `control_store.py` |

→ **[L3](L3/confinamento-filesystem.md)**

### 1.2 · Registry dei provider e ladder dei modelli

> **Responsabilità.** Confinare il vendor nell'adattatore; dichiarare le capacità invece di
> dedurle; normalizzare gli errori in una tassonomia comune; esporre tre gradini di modello
> con una regola di precedenza esplicita.

| | |
|---|---|
| **Ingressi** | descriptor di modello, configurazione, override di sessione o messaggio |
| **Uscite** | client del modello, usage normalizzato, `ProviderError` tipizzato |
| **Stato** | gradino corrente della ladder (muta solo in `escalate()`) |
| **Siti** | `providers.py`, `middleware.py`, `model_errors.py`, `model_preflight.py`, `pricing.py` |

→ **[L3](L3/registry-provider-e-ladder.md)**

---

## Stadio 2 · Assemblaggio del contesto

### 2.1 · Budget di contesto e compaction

> **Responsabilità.** Misurare l'occupazione della finestra, decidere l'azione minima
> sufficiente a rientrare, e lasciarne l'esecuzione a chi la applica.

La decisione è separata dall'esecuzione: la politica è testabile offline e l'azione può
essere emessa come evento prima di essere applicata.

| | |
|---|---|
| **Ingressi** | lista dei messaggi, soglie da `Settings` |
| **Uscite** | `ContextAction` |
| **Stato** | file di offload nel workspace |
| **Dipendenze** | usata anche dalla sandbox per gli output lunghi |
| **Siti** | `context_budget.py`, `context_monitor.py` |

→ **[L3](L3/budget-di-contesto.md)**

### 2.2 · Progressive disclosure delle skill

> **Responsabilità.** Esporre le skill per nome e descrizione, caricarne il corpo solo su
> invocazione, e trattare l'installazione da fonti esterne come la superficie d'attacco che è.

| | |
|---|---|
| **Ingressi** | cartella skill della sessione; archivi, URL, git, registry |
| **Uscite** | skill disponibili al modello; log delle installazioni |
| **Stato** | filesystem delle skill, ricopiato a ogni run |
| **Siti** | `skills.py`, `factory.py`, `control_store.py` |

→ **[L3](L3/progressive-disclosure-skill.md)**

---

## Stadio 3 · Esecuzione del turno

### 3.1 · Igiene dei blocchi-file verso il provider

> **Responsabilità.** Impedire che un file allegato malformato faccia rifiutare l'intera
> richiesta dal provider, rendendo la conversazione irrecuperabile a ogni turno successivo.

Unità piccola con una ragione d'essere non deducibile dal codice: l'errore che previene è
persistente e auto-riproducente.

| | |
|---|---|
| **Ingressi** | messaggi della richiesta, a ogni chiamata al modello |
| **Uscite** | messaggi con i blocchi corrotti sostituiti da una nota |
| **Stato** | nessuno |
| **Siti** | `file_guard.py`, `factory.py` |

→ **[L3](L3/igiene-blocchi-file.md)**

---

## Stadio 4 · Esecuzione guardata degli effetti collaterali

Lo stadio più denso. Tre unità che si toccano ma non vanno confuse.

### 4.1 · Approvazione di azioni sensibili (HITL)

> **Responsabilità.** Decidere se una tool call sensibile può procedere, sospendere il run
> quando serve una decisione umana, raccoglierla su qualunque superficie (CLI o web),
> riprendere il grafo con quella decisione.

| | |
|---|---|
| **Ingressi** | tool call; policy `interrupt_on`; stato `auto_approve` della sessione |
| **Uscite** | esecuzione del tool, oppure rifiuto restituito al modello come osservazione |
| **Stato** | run in `waiting_approval`; interrupt persistito; future in memoria |
| **Dipendenze** | `command_review` (classificazione), `durable` (persistenza), SSE (notifica) |
| **Siti** | `factory.py`, `runner.py`, `server.py`, `cli.py`, `durable.py`, `command_review.py`, `ApprovalDialog.tsx` |

**Invarianti.** La rete della sandbox richiede sempre conferma esplicita, anche in modalità
autonoma. Aggiungere un server MCP richiede sempre conferma esplicita. Il payload mostrato
all'utente è ricostruito, non inoltrato grezzo.

→ **[L3](L3/approvazione-azioni-sensibili.md)**

### 4.2 · Azione utente sbloccante

> **Responsabilità.** Fermare il run quando serve qualcosa che *solo un umano può fare nel
> mondo reale* — consenso OAuth, token da incollare, file di credenziali, 2FA — e riprendere
> con il valore ottenuto.

Distinta da 4.1: lì si chiede **permesso** per un'azione che l'agente sa fare, qui
**collaborazione** per un'azione che non può fare. Non esiste auto-risoluzione.

| | |
|---|---|
| **Ingressi** | chiamata del tool `request_user_action` |
| **Uscite** | valore fornito dall'utente, o segnale di annullamento |
| **Stato** | run in `waiting_action`; interrupt durevole di tipo `user_action` |
| **Siti** | `interaction.py`, `runner.py`, `server.py`, `UserActionDialog.tsx` |

→ **[L3](L3/azione-utente-sbloccante.md)**

### 4.3 · Esecuzione in sandbox

> **Responsabilità.** Eseguire il comando approvato in un container Docker dedicato alla
> sessione, senza rete salvo concessione per singolo comando, con capability rimosse e limiti
> fermi; catturare l'output e ripulire.

È il *dopo* di 4.1: riceve solo ciò che ha superato il gate. Detiene la seconda metà
dell'invariante «rete sempre gated» — la revoca nel `finally`.

| | |
|---|---|
| **Ingressi** | comando approvato, timeout, flag di rete |
| **Uscite** | output combinato, o stringa di errore leggibile dal modello |
| **Stato** | container per sessione, rete `--internal`, file di offload |
| **Siti** | `sandbox.py`, `docker/` |

→ **[L3](L3/esecuzione-in-sandbox.md)**

---

## Stadio 5 · Continuazione e verifica

### 5.1 · Continuazione Ralph-style
### 5.2 · Verifica a rubric

> **Responsabilità.** Reiniettare l'obiettivo finché il lavoro non supera i controlli, entro
> un budget; impedire che `[GOAL_COMPLETE]` chiuda un run senza verifica; misurare la
> difficoltà invece di prevederla, salendo di gradino solo dopo un fallimento osservato.

Documentate insieme: il grader non ha un grafo proprio, reinietta il feedback nello stesso
budget di continuazione.

| | |
|---|---|
| **Ingressi** | obiettivo, messaggi del turno, esito del grader |
| **Uscite** | `RunResult` con `terminal_status` e `failure_reason` |
| **Stato** | gradino della ladder, contatore di iterazioni |
| **Siti** | `runner.py`, `verification.py`, `outcome_checks.py`, `prompts.py` |

→ **[L3](L3/continuazione-e-verifica.md)**

### 5.3 · Budget di run

> **Responsabilità.** Prenotare e contabilizzare token, costo, chiamate e tempo con
> prenotazioni concorrenti; fermare il run indicando quale dimensione è esaurita.

| | |
|---|---|
| **Ingressi** | richieste al modello da root, router, grader e subagenti |
| **Uscite** | snapshot osservabile; `BudgetExceededError` con dimensione |
| **Stato** | ledger condiviso sotto lock |
| **Siti** | `run_budget.py`, `usage.py`, `pricing.py` |

→ **[L3](L3/budget-di-run.md)**

---

## Stadio 6 · Persistenza e proiezione

### 6.1 · Lavoro durevole

> **Responsabilità.** Rendere sopravvivibile al riavvio ciò che altrimenti muore col
> processo: stato del run, coda con lease, interrupt pendenti, idempotenza dei side effect.

Due garanzie centrali: transizioni con optimistic locking, idempotency key su ogni side
effect.

| | |
|---|---|
| **Ingressi** | transizioni di stato, claim, risoluzioni di interrupt |
| **Uscite** | stato durevole; `InvalidTransition` sui conflitti |
| **Stato** | SQLite (`work_items`, `interrupts`) |
| **Siti** | `durable.py`, `server.py` |

→ **[L3](L3/lavoro-durevole.md)**

### 6.2 · Contratto di evidenza e gate di delivery

> **Responsabilità.** Produrre un manifest hashato di ciò che il run ha fatto, verificarlo
> con un checker indipendente su una copia read-only, e legare l'approvazione umana di
> delivery all'hash di quel manifest specifico.

Il principio: l'agente non è la fonte di verità su ciò che ha fatto.

| | |
|---|---|
| **Ingressi** | artefatti del workspace, eventi della trace, provenienza git |
| **Uscite** | manifest, integrità, esito del checker, prontezza di delivery |
| **Stato** | bundle read-only per run, decisione di gate |
| **Siti** | `evidence.py`, `server.py`, `control_store.py` |

→ **[L3](L3/evidenza-e-delivery-gate.md)**

---

## Stadio trasversale · Autonomia e governance

### T.1 · Delega a subagenti

> **Responsabilità.** Validare il piano di delega proposto dal modello contro il roster
> reale, eseguirlo con contesto isolato e privilegi minori del padre, e osservarne l'esito.

Il piano del modello è una proposta, non un ordine: agenti inventati, ID duplicati,
dipendenze inesistenti e grafi ciclici vengono rimossi prima dell'esecuzione.

| | |
|---|---|
| **Ingressi** | piano strutturato dal modello, roster, profili di tool |
| **Uscite** | piano validato, esecuzioni osservabili, risultati testuali al padre |
| **Stato** | esecuzioni per task, semaforo di parallelismo |
| **Siti** | `subagent_routing.py`, `subagents.py`, `factory.py`, `run_budget.py` |

→ **[L3](L3/delega-a-subagenti.md)**

### T.2 · Trigger autonomi

> **Responsabilità.** Avviare run senza un umano davanti, da cron o webhook, senza mai
> eseguire due volte lo stesso istante e senza mai trattare il payload di un webhook come
> istruzione.

| | |
|---|---|
| **Ingressi** | espressioni cron con fuso; richieste webhook autenticate da token |
| **Uscite** | run avviati |
| **Stato** | cache dei minuti già scattati, reclamo durevole |
| **Dipendenze** | `durable.claim_once` per la garanzia «una volta sola» |
| **Siti** | `triggers.py`, `server.py`, `durable.py` |

→ **[L3](L3/trigger-autonomi.md)**

### T.3 · Ciclo di self-improvement

> **Responsabilità.** Proporre modifiche entro una whitelist a partire dalle trace,
> confrontare baseline e candidato su un eval set versionato, applicare un gate canary live,
> promuovere o fare rollback — senza mai toccare il codice.

Sei vincoli, tutti contro la stessa scorciatoia: imparare a *sembrare* migliore. Rubric e
soglia restano fuori dalla whitelist.

| | |
|---|---|
| **Ingressi** | run terminali recenti e trace correlate; eval set versionato |
| **Uscite** | proposta, esito del gate, metriche canary, versione promossa |
| **Stato** | `state/improvements/`, versioni di config, canary attiva |
| **Siti** | `improve.py`, `evaluation.py`, `canary.py`, `promotion.py` |

→ **[L3](L3/self-improvement.md)**
