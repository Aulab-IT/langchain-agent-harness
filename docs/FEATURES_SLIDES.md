# Agent Harness — Feature & Tecniche

> Deck di riferimento. Ogni `##` è pensato come una slide.
> Due chiavi di lettura: **Harness Engineering** (cosa trasforma un modello in agente) e
> **Loop Engineering** (cosa fa migliorare e ripetere l'agente nel tempo).

---

## 1. Di cosa parliamo

Un **agent harness** è tutto ciò che sta *intorno* al modello e lo rende un agente affidabile:
prompt, strumenti, filesystem, sandbox, memoria, gestione del contesto, pianificazione,
subagenti, approvazioni umane, verifica.

Il **loop engineering** è lo strato che chiude il cerchio: trigger, valutazione, continuazione,
escalation, self-improvement — l'agente che *ripete* un compito e *migliora* nel tempo.

Riferimenti: *The Anatomy of an Agent Harness* e *The Art of Loop Engineering* (LangChain).

---

## 2. Architettura a colpo d'occhio

```
CLI / Control Center (React)
 └─ GoalRunner
     ├─ approvazione (human-in-the-loop) + budget di continuazione
     └─ LangGraph / Deep Agent
         ├─ modello + router a 3 gradini
         ├─ planning + compaction del contesto
         ├─ filesystem + memoria + skills
         ├─ tool locali, web, MCP
         ├─ subagenti isolati
         ├─ audit + limiti + guardie
         └─ checkpoint SQLite
 └─ Control plane di self-improvement
     ├─ trace correlati → proposta → eval baseline/candidato
     ├─ regression gate → canary live → promotion versionata → rollback
     └─ durable store (idempotenza, interrupt persistiti)
```

---

# Parte I — Harness Engineering

---

## 3. Prompt di sistema come contratto

- **Regole operative** esplicite: pianificare per compiti >2 azioni, leggere prima di scrivere,
  delegare ricerca/revisione ai subagenti, trattare web/file/tool come **dati non attendibili**.
- **Azioni irreversibili**: mai `rm -rf` sulla radice, mai cancellare file non creati nel run;
  una richiesta distruttiva richiede conferma esplicita.
- **Marcatore di completamento** `[GOAL_COMPLETE]` solo dopo verifica.
- **Nudge mirati** (aggiunti sul campo): operazioni indipendenti in parallelo; per installare
  skill usa `skill_install`, mai `npx` nella sandbox; per file binari usa `docker_exec`+pypdf,
  mai `write_file`.

---

## 4. Strumenti dell'agente

| Tool | Cosa fa | Confine |
|---|---|---|
| `docker_exec` | Esegue codice in sandbox effimera | Isolamento Docker, rete on-demand |
| filesystem | Legge/scrive | Solo `/workspace` e `/memories` |
| `browser_read` | Legge pagine web | Difese SSRF (no IP privati/loopback, limite dimensione) |
| `web_search` | Ricerca fonti recenti | Risultati = dati non attendibili |
| `skill_*` | Gestisce le skill | In-process, host |
| `propose_mcp_server` | Propone un server MCP | **Sempre** con approvazione umana |
| `request_user_action` | Chiede un passo all'utente (OAuth, upload) | Ferma il run finché non rispondi |

---

## 5. Esecuzione in sandbox (sicurezza)

- **Container Docker effimero per sessione**, avviato on-demand, riusato tra i comandi.
- **Confini**: filesystem root in sola lettura, **capability Linux rimosse** (`--cap-drop ALL`),
  `no-new-privileges`, utente non-root, solo `/workspace` scrivibile.
- **Rete disattivata di default**; concessa **per singolo comando e solo su conferma**
  (`with_network`), poi revocata — anche in modalità autonoma la rete richiede sempre l'ok.
- **Rete `--internal` per-sessione**: isolamento tra sessioni equivalente a `none`.
- **Limiti risorse** dimensionati per lavoro reale: 2 GB RAM, 2 core, `/tmp` 512 MB, pids 512.
- **Robustezza output**: cattura byte grezzi e decodifica con `errors="replace"` → un comando
  con output binario non fa più crashare il run (`UnicodeDecodeError`).

---

## 6. Filesystem confinato + offload degli output lunghi

- Lettura/scrittura **solo dentro il workspace**; nessun path fuori dal confine.
- Il workspace è **memoria operativa**: risultati lunghi, note, artefatti intermedi su file.
- **Convenzione `output/`**: solo i deliverable finali vengono allegati alla chat; gli
  intermedi restano in cartelle dedicate.
- **Offload degli output di tool lunghi**: un `docker_exec` che stampa molto salva l'integrale
  in `/workspace/.tool_output/<checksum>.txt` e nel contesto entra solo estratto + riferimento
  recuperabile → meno token, nessuna perdita (54 KB → ~1,6 KB in contesto).

---

## 7. Memoria continua (stile AGENTS.md)

- **Due livelli**: template globale `memories/AGENTS.md` (seme di ogni sessione) e **copia
  per-sessione**, seminata una volta e poi persistente — l'agente ci scrive i propri apprendimenti.
- **Sempre iniettata** nel prompt: preferenze durevoli, non chiacchiere.
- **Promozione manuale** sessione → template, mai automatica (difesa da prompt-injection
  cross-sessione: una sessione non detta istruzioni a tutte le altre senza revisione umana).
- **Cap di dimensione**: la memoria scritta dall'agente non può crescere senza limite (evento
  `memory.truncated` visibile); i token della memoria sono mostrati nel pannello.

---

## 8. Skills — progressive disclosure

- Le **skill** sono procedure caricate *su richiesta*: nel prompt entra solo nome+descrizione,
  il corpo si legge quando serve → contesto leggero.
- **Creazione/modifica** da agente (`skill_create`, `skill_write_file`) e da UI.
- **Installazione da fonti esterne** (`skill_install`): `git` (repo + `subdir`), `archive_url`
  (.zip/.tar.gz), `registry` (agentskills.io). Estrazione blindata: no traversal/symlink/size-bomb,
  validazione contro lo standard, audit dell'installazione.
- **skill-creator**: la skill che insegna a scrivere skill conformi.
- Errori d'installazione **tornano al modello** come osservazione, non fanno crashare il run.

---

## 9. Gestione del contesto (context engineering)

- **Budget applicato**, non solo mostrato: finestra utile = finestra − output riservato; soglie
  di warning (70%) e compaction (80%).
- **`ContextMonitorMiddleware`**: emette `context.snapshot` (al cambio di pressione) e
  **`context.compaction.detected`** con token prima/dopo — la compaction diventa *visibile*.
- **Compaction automatica** (deepagents) sulla finestra reale del modello + **compaction
  manuale** on-demand (tool `compact_conversation` + pulsante "Compatta").
- **`LiveUsageThrottle`**: un solo evento `usage.live` al secondo (prima ~33k eventi/run).
- **Guardia sui blocchi-file corrotti**: un file malformato (es. PDF finto) viene sostituito con
  una nota prima di raggiungere il provider → non avvelena più la conversazione (400 `invalid_file`).

---

## 10. MCP — Model Context Protocol

- **Multi-server** configurabile da `state/mcp.json` (formato standard `mcpServers`), con segreti
  via `${VAR}` espansi dall'ambiente (mai nel file).
- **Server interno in-process**: i tool didattici (`skill_*`, `count_text`, glossario) girano nel
  processo dell'agente — **build run 3,7 s → 0,055 s**, niente subprocess a ogni tool-call.
- **Server esterni** fuori processo (dove l'isolamento conta), con **resilienza per-server**: uno
  che non risponde genera `mcp.server.failed` e non blocca il run.
- **Auto-estensione controllata**: l'agente può **proporre** un nuovo server MCP; l'aggiunta passa
  *sempre* da approvazione umana (uno stdio gira sull'host, fuori dalla sandbox).

---

## 11. Subagenti isolati

- **Researcher** e **Reviewer** con **contesto proprio**: non inquinano quello del coordinatore.
- Il researcher tratta le fonti come dati non attendibili e restituisce sintesi con URL.
- Il reviewer è di sola lettura: controlla requisiti, coerenza, rischi e prove di verifica.
- I subagenti girano su gradini economici: solo l'agente principale può salire al gradino alto.

---

## 12. Astrazione dei provider

- **Registry provider-neutral**: OpenAI, **Anthropic (Claude)**, e locali **Ollama / MLX** su
  Apple Silicon — ogni gradino sceglie il proprio vendor, senza toccare il codice.
- Chiavi e assegnazione gradini **modificabili da UI**, attive dal run successivo (no riavvio),
  chiavi **mai** esposte in chiaro.
- Cost accounting con **listino versionato** per provider/modello.

---

## 13. Human-in-the-loop

- **Approvazione** sui comandi sensibili (`docker_exec`); la **rete** richiede *sempre* conferma,
  anche in modalità autonoma.
- **Azioni utente sbloccanti** (`request_user_action`): OAuth nel browser, upload credenziali,
  incolla token — il run si ferma e riprende con la risposta.
- **Classificazione statica** del comando mostrata prima dell'approvazione (spiegazione, non
  autorizzazione).
- **Errori leggibili**: un fallimento del provider (file corrotto, rate limit, auth, contesto
  pieno) diventa un messaggio azionabile in UI, non un generico "esecuzione fallita".

---

## 14. Osservabilità

- **Audit** senza contenuti sensibili; **trace** in diretta (azione corrente, durata, tool).
- **Timeline cross-run** a cascata di ogni tool call con argomenti/output.
- **Pannello Contesto**: token per categoria (system, conversazione, tool, file), barra colorata
  sulle soglie di pressione.
- **Timer generale** del run (min:sec) sincronizzato tra topbar e card d'attesa.

---

# Parte II — Loop Engineering

---

## 15. Il ciclo di completamento

- **`GoalRunner`**: obiettivo → esecuzione → verifica → (eventuale) continuazione.
- **Budget di continuazione**: max N iterazioni; ogni continuazione riprende da file e piano
  persistenti, senza ripetere lavoro fatto.
- **Verifica prima di dichiarare fatto**: euristica «serve prova in sandbox?» (verbi IT+EN,
  limitata al turno corrente) + grader a rubrica.

---

## 16. Model routing: misurare, non predire

- **Scala a 3 gradini** (basso/medio/alto): modello e reasoning effort salgono insieme.
- **Non si predice la difficoltà dalle parole chiave** (nessuna lingua privilegiata): si parte
  dal gradino più economico e **si sale solo se il gradino ha fallito** il criterio d'uscita.
- **Due soglie, due domande**: «obiettivo raggiunto?» (rubric, 0,70) e «questo gradino ce la fa?»
  (escalation, 0,50). Tra le due, si riprova **con lo stesso modello**.
- Costa un'iterazione in più sui compiti difficili; costava 5× tanto su quelli facili con la
  parola sbagliata.

---

## 17. Verifica a rubrica (il grader)

- Un modello **giudica** la risposta contro una rubrica congelata → punteggio + feedback.
- Il feedback alimenta la **continuazione**: l'agente corregge i punti indicati con prove.
- Il grader gira una volta per iterazione, sul gradino medio — mai sull'alto.
- **Calibrazione**: `calibrate_grader.py` verifica che il grader separi risposte buone da cattive
  (`max(cattive) < min(buone)`), prerequisito perché l'escalation non erediti rumore.

---

## 18. Trigger — run autonomi

- **Cron** timezone-aware con gestione corretta dell'ora legale; **webhook** con token dedicato.
- **Payload webhook** sempre trattato come **dato non attendibile**, mai istruzioni.
- **Criterio di successo** dichiarato alla creazione: dà al loop periodico un modo di sapere
  quando ha finito.
- **Idempotenza durevole**: un `(trigger, minuto)` scatta **una volta sola**, anche attraverso un
  riavvio del backend (garanzia persistita, non solo in memoria).
- **Skip visibile** (`trigger.skipped`) se la sessione è occupata; toggle scheduler da UI.

---

## 19. Self-improvement controllato (hill-climbing)

Ciclo completo, con revisione umana ad ogni gate:

1. **Weakness report**: aggrega gli ultimi run terminali e i trace correlati.
2. **Proposta** entro una whitelist (mai codice arbitrario: prompt addendum, limiti, ecc.).
3. **Eval paired** baseline vs candidato su `evals/cases.json` (ordine alternato per ridurre bias).
4. **Separazione dei segnali**: check deterministici sull'output, completion del protocollo,
   feedback del grader.
5. **Regression gate**: blocca regressioni di qualità, aumenti eccessivi di token/latenza e
   reward hacking.

---

## 20. Self-improvement — gate live e rollback

6. **Attribuzione baseline/canary** con **gate live**: metriche in tempo reale (success/failure,
   score, token e latenza medi, delta vs baseline), polling finché la canary è attiva.
7. **Promotion versionata** al 100% solo se il gate passa.
8. **Rollback** a qualunque configurazione precedente, da storico versionato.

Rubric e soglie restano **congelate**; le chiamate reali al modello avvengono solo dopo azione
esplicita.

---

## 21. Eval set come fondamenta

- `evals/cases.json`: casi con `goal`, fixture di file, **check deterministici**
  (`file_exists`, `file_contains`, `answer_contains/regex/not_contains`, `file_not_exists`,
  `max_tool_calls`).
- Copertura su **più lingue** (IT/EN) e difficoltà, casi di **sicurezza/integrità** e onestà
  («non inventare se il dato manca»).
- Più il set discrimina, più l'escalation è precisa → costo medio più basso a parità di qualità.

---

## 22. Parallelismo

- **Tool-call in parallelo**: le chiamate indipendenti di un turno vengono eseguite concorrenti
  (il framework le raccoglie con `gather`); un nudge nel prompt spinge l'agente a batcharle.
- **Multi-sessione concorrente**: sessioni diverse girano in parallelo, una run per sessione.

---

## 23. Durabilità (work durevole)

- **DurableStore** su SQLite: coda con lease, transizioni validate con optimistic locking,
  **idempotency key su ogni side effect**.
- **Interrupt persistiti**: approvazioni e azioni utente sopravvivono al riavvio; endpoint di
  ispezione mostra cosa era in attesa e non è stato risolto.
- **Recovery al boot**: nessun run resta "in esecuzione" fantasma dopo un crash.

---

## 24. Async & notifiche (pattern "cowork")

- **Run asincroni**: lanci un task, ti allontani, non blocchi la UI.
- **Centro notifiche** persistente: fine run, run fallito, «serve la tua approvazione/azione».
- **Toast in-app** in ogni tab + **notifica desktop** quando la tab non ha il focus → due sessioni
  in due tab si avvisano a vicenda.

---

## 25. Osservabilità del costo e dei token

- Semantica **unica** per token/contesto/costo tra CLI, API, eval e canary.
- **Ledger economico** per chiamata, run, sessione, modello e provider, da listino versionato.
- `context.snapshot` e `usage.snapshot` alimentano barre e timer in tempo reale.

---

## 26. Sintesi — cosa rende questo harness solido

- **Sicurezza per default**: sandbox, SSRF, rete on-demand, approvazioni, segreti mai in chiaro.
- **Contesto sotto controllo**: budget applicato, compaction visibile e manuale, offload, guardie.
- **Costo governato**: routing che misura, escalation a due soglie, subagenti economici.
- **Loop che migliora**: eval + grader calibrato + canary gate + rollback versionato.
- **Robustezza operativa**: durabilità, idempotenza, errori leggibili, recovery, notifiche.

---

## 27. Riferimenti

- *The Anatomy of an Agent Harness* — LangChain
- *The Art of Loop Engineering* — LangChain
- `docs/HARNESS_COMPONENTS.md` — matrice articolo → implementazione
- `docs/SELF_IMPROVEMENT.md` — formule del gate canary
