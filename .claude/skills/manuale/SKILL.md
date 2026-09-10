---
name: manuale
description: >-
  Mappa dei comportamenti di `langchain_harness`: dice quale unità governa un dato
  comportamento, quali file tocca e dove leggerne il dettaglio con l'evidenza nel
  codice. Usa questa skill PRIMA di cercare nel codice quando la domanda riguarda
  cosa fa il sistema — «perché il comando è stato bloccato?», «dove si decide X?»,
  «cosa devo toccare per cambiare Y?» — e prima di modificare un comportamento
  esistente. Un comportamento vive sparso in più file: cercare per parole chiave
  trova i posti sbagliati o ne trova troppi.
---

# Comportamenti di langchain_harness

Il manuale è organizzato per **comportamento**, non per modulo. Ogni affermazione
porta il punto esatto del codice che la rende vera. Le pagine stanno in `docs/handbook/`.

## Come usarla

1. **Trova l'unità** nell'indice qui sotto: cerca il comportamento, non il file.
2. **Apri la sua pagina L3.** Le ultime due sezioni sono quelle che servono a
   modificare: *Riepilogo evidenza* elenca i siti coinvolti, *Note per chi modifica*
   dice cosa toccare e quali invarianti non rompere.
3. **Segui le unità collegate.** Se due unità citano lo stesso file, un cambiamento
   in quel file le riguarda entrambe.
4. **Verifica contro il codice.** Il manuale guida la ricerca; la verità è il
   repository. Apri i file citati e conferma prima di concludere: le righe possono
   essersi spostate, e una pagina può descrivere codice cambiato.

Panoramica del flusso: `docs/handbook/L1_SISTEMA.md`. Indice completo con ingressi,
uscite e stato di ogni unità: `docs/handbook/L2_UNITA.md`.

## Le unità

### Stadio 1 · Configurazione e composizione

**1.1 · Confinamento del filesystem** — Garantire che ogni lettura e scrittura resti dentro la radice della sessione, indipendentemente dal path richiesto dal modello.
Tocca: `src/agent_harness/factory.py`, `src/agent_harness/control_store.py`, `src/agent_harness/config.py`.
→ `docs/handbook/L3/confinamento-filesystem.md`

**1.2 · Registry dei provider e ladder dei modelli** — Confinare il vendor nell'adattatore; dichiarare le capacità invece di dedurle; normalizzare gli errori in una tassonomia comune; esporre tre gradini di modello con una regola di precedenza esplicita.
Tocca: `src/agent_harness/providers.py`, `src/agent_harness/middleware.py`, `src/agent_harness/factory.py`, `src/agent_harness/model_errors.py`.
→ `docs/handbook/L3/registry-provider-e-ladder.md`

### Stadio 2 · Assemblaggio del contesto

**2.1 · Budget di contesto e compaction** — Misurare l'occupazione della finestra, decidere l'azione minima sufficiente a rientrare, e lasciarne l'esecuzione a chi la applica.
Tocca: `src/agent_harness/context_budget.py`.
→ `docs/handbook/L3/budget-di-contesto.md`

**2.2 · Progressive disclosure delle skill** — Esporre le skill per nome e descrizione, caricarne il corpo solo su invocazione, e trattare l'installazione da fonti esterne come la superficie d'attacco che è.
Tocca: `src/agent_harness/skills.py`, `src/agent_harness/config.py`, `src/agent_harness/control_store.py`, `src/agent_harness/factory.py`, `src/agent_harness/sandbox.py`.
→ `docs/handbook/L3/progressive-disclosure-skill.md`

### Stadio 3 · Esecuzione del turno

**3.1 · Igiene dei blocchi-file verso il provider** — Impedire che un file allegato malformato faccia rifiutare l'intera richiesta dal provider, rendendo la conversazione irrecuperabile a ogni turno successivo.
Tocca: `src/agent_harness/file_guard.py`, `src/agent_harness/factory.py`.
→ `docs/handbook/L3/igiene-blocchi-file.md`

### Stadio 4 · Esecuzione guardata degli effetti collaterali

**4.1 · Approvazione di azioni sensibili (HITL)** — Decidere se una tool call sensibile può procedere, sospendere il run quando serve una decisione umana, raccoglierla su qualunque superficie (CLI o web), riprendere il grafo con quella decisione.
Tocca: `src/agent_harness/server.py`, `src/agent_harness/factory.py`, `src/agent_harness/command_review.py`, `src/agent_harness/durable.py`, `src/agent_harness/cli.py`, `src/agent_harness/runner.py` e altri 3.
→ `docs/handbook/L3/approvazione-azioni-sensibili.md`

**4.2 · Azione utente sbloccante** — Fermare il run quando serve qualcosa che *solo un umano può fare nel mondo reale* — consenso OAuth, token da incollare, file di credenziali, 2FA — e riprendere con il valore ottenuto.
Tocca: `src/agent_harness/server.py`, `src/agent_harness/interaction.py`, `src/agent_harness/runner.py`, `client/src/App.tsx`, `client/src/components/shared/UserActionDialog.tsx`.
→ `docs/handbook/L3/azione-utente-sbloccante.md`

**4.3 · Esecuzione in sandbox** — Eseguire il comando approvato in un container Docker dedicato alla sessione, senza rete salvo concessione per singolo comando, con capability rimosse e limiti fermi; catturare l'output e ripulire.
Tocca: `src/agent_harness/sandbox.py`.
→ `docs/handbook/L3/esecuzione-in-sandbox.md`

### Stadio 5 · Continuazione e verifica

**5.1 · Continuazione Ralph-style** — Reiniettare l'obiettivo finché il lavoro non supera i controlli, entro un budget; impedire che `[GOAL_COMPLETE]` chiuda un run senza verifica; misurare la difficoltà invece di prevederla, salendo di gradino solo dopo un fallimento osservato.
Tocca: `src/agent_harness/runner.py`.
→ `docs/handbook/L3/continuazione-e-verifica.md`

**5.3 · Budget di run** — Prenotare e contabilizzare token, costo, chiamate e tempo con prenotazioni concorrenti; fermare il run indicando quale dimensione è esaurita.
Tocca: `src/agent_harness/run_budget.py`, `src/agent_harness/cli.py`, `src/agent_harness/pricing.py`.
→ `docs/handbook/L3/budget-di-run.md`

### Stadio 6 · Persistenza e proiezione

**6.1 · Lavoro durevole** — Rendere sopravvivibile al riavvio ciò che altrimenti muore col processo: stato del run, coda con lease, interrupt pendenti, idempotenza dei side effect.
Tocca: `src/agent_harness/durable.py`, `src/agent_harness/server.py`.
→ `docs/handbook/L3/lavoro-durevole.md`

**6.2 · Contratto di evidenza e gate di delivery** — Produrre un manifest hashato di ciò che il run ha fatto, verificarlo con un checker indipendente su una copia read-only, e legare l'approvazione umana di delivery all'hash di quel manifest specifico.
Tocca: `src/agent_harness/evidence.py`, `src/agent_harness/server.py`.
→ `docs/handbook/L3/evidenza-e-delivery-gate.md`

### Stadio trasversale · Autonomia e governance

**T.1 · Delega a subagenti** — Validare il piano di delega proposto dal modello contro il roster reale, eseguirlo con contesto isolato e privilegi minori del padre, e osservarne l'esito.
Tocca: `src/agent_harness/subagent_routing.py`, `src/agent_harness/factory.py`, `src/agent_harness/subagents.py`, `src/agent_harness/run_budget.py`.
→ `docs/handbook/L3/delega-a-subagenti.md`

**T.2 · Trigger autonomi** — Avviare run senza un umano davanti, da cron o webhook, senza mai eseguire due volte lo stesso istante e senza mai trattare il payload di un webhook come istruzione.
Tocca: `src/agent_harness/triggers.py`, `src/agent_harness/server.py`, `src/agent_harness/durable.py`.
→ `docs/handbook/L3/trigger-autonomi.md`

**T.3 · Ciclo di self-improvement** — Proporre modifiche entro una whitelist a partire dalle trace, confrontare baseline e candidato su un eval set versionato, applicare un gate canary live, promuovere o fare rollback — senza mai toccare il codice.
Tocca: `src/agent_harness/evaluation.py`, `src/agent_harness/improve.py`, `src/agent_harness/canary.py`, `src/agent_harness/promotion.py`.
→ `docs/handbook/L3/self-improvement.md`

## File toccati da più unità

Sono i punti in cui comportamenti diversi si incontrano: modificarli ne riguarda
più di uno.

- `src/agent_harness/factory.py` → unità 1.1, 1.2, 2.2, 3.1, 4.1, T.1
- `src/agent_harness/server.py` → unità 4.1, 4.2, 6.1, 6.2, T.2
- `src/agent_harness/config.py` → unità 1.1, 2.2, 4.1
- `src/agent_harness/durable.py` → unità 4.1, 6.1, T.2
- `src/agent_harness/runner.py` → unità 4.1, 4.2, 5.1
- `client/src/App.tsx` → unità 4.1, 4.2
- `src/agent_harness/cli.py` → unità 4.1, 5.3
- `src/agent_harness/control_store.py` → unità 1.1, 2.2
- `src/agent_harness/run_budget.py` → unità 5.3, T.1
- `src/agent_harness/sandbox.py` → unità 2.2, 4.3

## Se il manuale e il codice non concordano

Dillo invece di adattarti: significa che il codice è cambiato e la pagina è
rimasta indietro. `make handbook-check` verifica che ogni riferimento sia dove il
manuale dice.
