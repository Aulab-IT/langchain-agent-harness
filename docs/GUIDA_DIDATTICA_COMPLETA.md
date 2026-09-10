# Guida didattica completa all’Agent Harness

## 1. Obiettivo del progetto

Un modello linguistico trasforma messaggi in altri messaggi. Un agente affidabile deve anche scegliere
azioni, manipolare artefatti, ricordare stato, chiedere autorizzazioni, rispettare budget, verificare
risultati e spiegare perché un esito è credibile. L’**harness** è questo insieme di meccanismi attorno
al modello.

Questo repository ha due livelli coordinati:

- `src/agent_harness/` + `client/`: il sistema, con CLI, API FastAPI e Control Center React.
- `docs/handbook/`: il manuale che lo descrive **per comportamento** invece che per modulo, con
  l'evidenza `file · riga` di ogni affermazione e un gate di CI che verifica che ogni riferimento
  punti ancora al codice giusto.

L'accoppiata evita due errori comuni: mostrare un framework completo senza far capire i pezzi,
oppure scrivere documentazione che invecchia in silenzio mentre il codice si muove.

## 2. Modello mentale: quattro loop impilati

```text
Loop 4 · improvement: trace → proposta → eval → canary → promotion/rollback
Loop 3 · event-driven: cron/webhook → nuovo run
Loop 2 · verification: risultato → rubric/check → feedback → continuation
Loop 1 · agent: modello → tool → osservazione → modello
```

Il Loop 1 produce lavoro. Il Loop 2 impedisce di confondere una risposta fluida con un obiettivo
raggiunto. Il Loop 3 rende l’agente reattivo a eventi esterni. Il Loop 4 migliora configurazione solo
dopo confronto controllato. Ogni loop ha budget e condizioni terminali: nessuno è infinito.

## 3. Dal modello al loop agente

### 3.1 Chiamata diretta

Al livello più basso una lista di messaggi contiene istruzione di sistema, input utente e risposte.
È già un primo harness: decide formato, lingua e memoria del turno. Limite: il modello non può
ottenere nuove prove o causare effetti.

### 3.2 Tool calling e ReAct

Un tool è un contratto tipizzato: nome, descrizione, schema argomenti e risultato. `create_agent`
esegue ciclo:

1. modello riceve messaggi e schemi tool;
2. restituisce risposta oppure una o più tool call;
3. runtime valida ed esegue tool;
4. osservazione torna nel contesto;
5. modello decide passo successivo.

Tipi e docstring non sono decorazione: sono parte del prompt. Tool sovrapposti o vaghi aumentano
selezioni errate e token. Il catalogo finale registra tool locali, browser, ricerca, sandbox e MCP,
ma espone solo quelli abilitati dalla configurazione.

### 3.3 Stato, checkpoint e thread

Una cronologia Python sparisce al riavvio. LangGraph salva stato in checkpoint SQLite. `thread_id`
è chiave di isolamento: stesso id continua conversazione; id diverso riparte con stato distinto.
Checkpoint conserva stato del graph, non sostituisce file, memoria lunga o coda operativa.

## 4. Filesystem e sandbox

### 4.1 Workspace come memoria operativa

Output grandi e artefatti non devono vivere tutti nel prompt. Il filesystem offre spazio stabile per
piano, codice, report e prove. Ogni sessione del Control Center usa directory separata. Tutti i path
vengono risolti e verificati contro root: `../`, symlink e path assoluti fuori confine vengono rifiutati.

### 4.2 Perché un subprocess non è una sandbox

Un processo Python con timeout può ancora leggere home, rete e segreti host: il timeout limita la
durata, non l'accesso. Il sistema finale usa Docker con:

- root filesystem read-only;
- utente non-root, capability rimosse e `no-new-privileges`;
- rete disabilitata salvo flusso approvato;
- limiti CPU, memoria, PID e tempo;
- sola directory workspace montata in scrittura;
- nessun socket Docker, home o segreto host montato.

`command_review.py` classifica il comando prima dell’esecuzione. Modalità auto-approve non autorizza
automaticamente rete. Docker riduce superficie, ma non rende sicuro esporre il sistema a utenti ostili.

## 5. Web, ricerca e MCP

`browser_read` accetta solo HTTP/HTTPS, risolve host, blocca loopback e IP privati, limita redirect e
dimensione risposta, elimina contenuto eseguibile. HTML recuperato è **dato non attendibile**: una pagina
può contenere prompt injection, quindi non può cambiare istruzioni del sistema.

Ricerca web e lettura pagina sono distinte: la prima trova candidati recenti, la seconda acquisisce
contenuto. MCP aggiunge tool da processi o servizi esterni tramite protocollo comune. Config MCP finale:

- supporta più server;
- valida trasporto e comando;
- mantiene tool built-in in-process per evitare overhead;
- attribuisce origine/server nella UI;
- tratta metadati e output remoti come non attendibili.

MCP standardizza il collegamento, non rende automaticamente affidabile server o tool.

## 6. Contesto, memoria e skill

### 6.1 Quattro cose diverse

| Meccanismo | Scopo | Durata |
|---|---|---|
| Messaggi/checkpoint | conversazione corrente | per thread |
| Workspace | artefatti e stato operativo | per sessione |
| Memoria | preferenze/conoscenza stabile | tra sessioni |
| Skill | procedura riutilizzabile | catalogo versionato |

Scrivere tutto in `AGENTS.md` gonfia ogni prompt. Trasformare ogni preferenza in skill rende difficile
capire ciò che vale sempre. Il sistema carica memoria breve e controllata nel prompt; le skill vengono
scoperte da descrizione e caricate integralmente solo quando servono (**progressive disclosure**).

### 6.2 Budget del contesto

`ContextBudgetManager` stima categorie: system prompt, messaggi utente/modello, tool output e contenuto
ricostruibile. Riserva spazio alla risposta finale e decide in ordine economico:

1. keep sotto soglia;
2. offload di tool output lungo su file, lasciando riferimento, checksum ed estratto;
3. rimozione di osservazioni duplicate ricostruibili;
4. summary strutturato con obiettivo, vincoli, decisioni, open item e artefatti;
5. stop controllato se nessuna riduzione rende la finestra sicura.

Compaction è loss-aware, non semplice troncamento. Il checksum consente di recuperare e verificare
l’output integrale.

## 7. Pianificazione e verifica

Deep Agents offre todo middleware; `/plan.md` rende piano visibile anche fuori contesto. Un buon piano
non è monologo iniziale: cambia quando tool restituiscono nuove prove.

Verifica avviene a più livelli:

- check deterministici: file esiste, contenuto atteso, regex, exit code, test;
- verifica ambiente: comando sandbox riuscito per task mutativi;
- rubric grader: completezza, aderenza, prove e sicurezza;
- safety veto: una violazione di sicurezza non viene mediata da altri punteggi;
- continuation: feedback specifico rientra nel loop entro budget.

`completed` non significa “modello ha scritto fatto”. Runner accetta terminalità solo quando outcome e
prove richieste passano; altrimenti usa stati `incomplete`, `failed_verification`, `budget_exceeded`,
`security_stop`, `blocked_needs_human` o `no_work`.

## 8. Subagenti e routing

Un subagente ha prompt, tool e contesto propri. Serve quando isolamento, parallelismo, revisione
indipendente o specializzazione offrono vantaggio concreto. Non serve per spezzare artificialmente un
task breve: delegare aggiunge chiamate, costo e punti di errore.

Il roster finale dichiara per ogni agente:

- capability e descrizione semantica;
- input/output attesi;
- tool e vincoli;
- tier modello;
- permessi read-only/write.

Un planner strutturato propone `DelegationPlan`; `validate_plan` applica codice deterministico:

- rimuove agenti, tool e dipendenze inventate;
- verifica capability e least privilege;
- blocca grafi ciclici;
- elimina discendenti di prerequisiti invalidi;
- richiede reviewer diverso dall’autore;
- preferisce root quando ha già tool adeguato e nessuna specializzazione è pertinente.

Root, grader e subagenti condividono `RunBudgetTracker`. Il risultato subagente segue protocollo con
stato, evidenza e artefatti; testo plausibile senza prove non autorizza completamento.

## 9. Provider, routing modelli e costi

### 9.1 Astrazione corretta

`providers.py` non riduce provider a nome modello. `ModelDescriptor` include capability, finestra,
execution kind, pricing key e reasoning effort. Adapter costruisce SDK, normalizza usage e classifica
errori in categorie comuni: rate limit, timeout, auth, context length, unavailable e bad request.

Capability locali sono deny-by-default finché probe non le verifica. Questo evita di inviare structured
output o tool paralleli a endpoint OpenAI-compatible che non li implementano davvero.

### 9.2 Scala low → mid → high

Ogni obiettivo parte economico. Escalation dipende da fallimento misurato—grader sotto soglia o prova
ambiente fallita—non da keyword linguistiche. Tra soglia rubric ed escalation, stesso tier riceve un
secondo tentativo. Override sessione può fissare tier.

### 9.3 Ledger del run

Budget contesto limita una singola finestra; budget run somma tutte le chiamate. Prima di ogni call il
tracker prenota input, output e costo. Chiamate parallele vedono le riserve già impegnate. Dopo risposta,
usage reale riconcilia prenotazione. Limiti includono:

- token e costo totali;
- durata;
- chiamate modello;
- invocazioni e chiamate modello per subagente;
- quota token per subagente;
- riserva obbligatoria per finalizzazione.

Warning 70/85/95% sono eventi osservabili; superamento produce hard stop terminale.

## 10. Human-in-the-loop e lavoro durevole

HITL serve per autorizzazione, non per correggere ogni scelta. Tool sensibili generano interrupt con
descrizione redatta; UI/CLI risponde approve/reject. `request_user_action` gestisce login, 2FA o file
mancanti senza fingere che il modello possa completare azione esterna.

Oggetti `asyncio.Task` e future in RAM non sopravvivono a restart. `DurableStore` aggiunge:

- coda SQLite e state machine;
- idempotency key per doppio invio/trigger;
- claim con lease recuperabile;
- optimistic locking tramite versione;
- retry con backoff e dead-letter;
- interrupt persistenti e risoluzione idempotente.

Effetti esterni richiedono comunque idempotenza end-to-end: persistere il run non impedisce doppia email
se provider remoto non riconosce stessa chiave.

## 11. Eventi, trace e Control Center

`server.py` espone API locale FastAPI; `control_store.py` conserva sessioni, messaggi, run, eventi,
usage, file e decisioni. SSE invia delta e stato senza rendere frontend proprietario del loop.

Control Center React offre:

- chat multi-turno, stop, allegati, modello forzato e sandbox mode;
- inspector con trace live, timeline, context, budget, file, memory, capability ed Evidence;
- gestione sessioni, skill, subagenti, MCP e impostazioni provider/runtime;
- dialog approvazione e user action;
- trigger cron/webhook;
- eval, canary, promotion e rollback.

File attivi (`html`, `svg`) non vengono serviti inline. Preview testo arriva come JSON; download usa
attachment. API ascolta `127.0.0.1`: progetto è local-first, single-user, non servizio pubblico con
auth/tenancy.

## 12. Loop engineering: trigger e miglioramento controllato

### 12.1 Trigger

Cron genera esecuzioni temporali; webhook usa token dedicato. Payload esterno viene delimitato come
dato, mai concatenato al system prompt come istruzione fidata. Idempotenza evita doppio fire.

### 12.2 Propose-only

`improve.py` sintetizza weakness report da run terminali e trace correlati. Modello può proporre solo
campi whitelisted (`system_prompt_addendum`, `harness_max_tool_calls`). Non modifica direttamente
codice/config attiva. Rubric e soglia sono congelate contro reward hacking.

### 12.3 Eval e gate

Baseline e candidato girano su stessi casi in workspace/thread separati. Check output e protocollo di
completion restano metriche distinte. Gate richiede zero regressioni deterministiche, pavimento di
qualità/completion, limiti token/latenza e miglioramento misurabile.

### 12.4 Canary e rollback

Hash stabile del `session_id` assegna stessa sessione allo stesso arm. Gate live parte dopo campione
minimo e verifica non-inferiorità. Promotion salva snapshot pre/post; rollback aggiunge nuova versione
senza riscrivere cronologia.

## 13. Manifest di evidenza e delivery

Una risposta è narrativa; un dossier è verificabile. `EvidenceManifest` include:

- hash input/output;
- stato terminale e contratto richiesto;
- artefatti con path, size e SHA-256;
- comandi con preview redatta, hash raw, exit code e durata;
- verifier e score;
- ambiente e provenienza Git/CI/preview;
- confine delivery e rollback plan.

Hash del manifest usa JSON canonico. Bundle copia artefatti in snapshot separato read-only; checker
indipendente opera sulla copia. Modifica di file o manifest viene rilevata.

Successo run e delivery sono decisioni separate. Merge, deploy e migrazioni richiedono insieme:
integrità, checker, branch non protetto, worktree pulito, CI verde, preview, rollback e approvazione
umana legata all’hash. Approvazione non annulla gate tecnici; nuova modifica invalida approvazione.

## 14. Sicurezza per confini

| Confine | Rischio | Difesa |
|---|---|---|
| Modello → filesystem | path traversal/symlink | root resolution, allowlist, session isolation |
| Modello → shell | comando arbitrario | review, HITL, container, limiti |
| Modello → rete | SSRF/esfiltrazione | URL/IP guard, rete revocabile, approval |
| Web/MCP → modello | prompt injection | contenuto marcato non attendibile |
| Upload → UI | contenuto attivo | size/type allowlist, JSON preview, attachment |
| Trace → storage | segreti | redazione e hash raw separato |
| Modello → config | reward hacking | whitelist, eval, canary, rollback |
| Run → delivery | azione irreversibile | evidence contract + human gate |

Sicurezza è composizione. Nessuna singola misura—Docker, approval o grader—copre tutti i confini.

## 15. Come studiare ed estendere

Percorso consigliato:

1. leggi `handbook/L1_SISTEMA.md` per gli stadi che una richiesta attraversa;
2. scegli in `handbook/L2_UNITA.md` l'unità di comportamento che ti interessa e scendi alla sua
   pagina L3: trigger, cambi di stato, percorsi di eccezione, casi limite;
3. apri i file citati dalle ancore, non l'albero dei sorgenti in ordine alfabetico;
4. usa la matrice di copertura per passare da concetto a modulo e test;
5. avvia API e client solo dopo aver capito confini di workspace, budget e HITL;
6. guarda Trace e Timeline durante un run vero: sono gli stessi stadi di L1, in diretta.

Per aggiungere un tool:

1. definisci schema minimo e output limitato;
2. stabilisci origine e trust level;
3. aggiungi confinement/timeout/redazione;
4. decidi se richiede approval o rete;
5. emetti eventi correlati;
6. aggiungi verifica deterministica e test offline;
7. documenta il comportamento nella pagina L3 dell'unità che lo governa, con l'evidenza nel
   codice, e aggiorna la matrice di copertura.

Per aggiungere provider o subagente, usa stessa disciplina: capability esplicite, deny-by-default,
budget, protocollo terminale e prove.

## 16. Limiti intenzionali

Il progetto è reference implementation locale avanzata, non piattaforma production multi-tenant.
Mancano autenticazione, tenancy, secret broker, deployment orchestrator e resilienza distribuita.
Docker non è confine perfetto contro workload ostili. Grader LLM resta probabilistico e va calibrato.
Frontend ha lint/build ma copertura test inferiore al backend. Questi limiti sono parte della lezione:
un harness affidabile dichiara ciò che non garantisce.

## 17. Comandi di verifica

```bash
uv sync --extra dev
make test
make lint
make handbook-check
cd client && npm run lint && npm run build
```

Dopo aver toccato un file citato dal manuale, prima del commit:

```bash
make handbook
```

Avvio sistema completo:

```bash
make sandbox-image
make run
```

La corrispondenza completa fra funzionalità, implementazione e test è in
[`MATRICE_COPERTURA_DIDATTICA.md`](MATRICE_COPERTURA_DIDATTICA.md); la mappa dei comportamenti,
con l'evidenza nel codice, in [`handbook/README.md`](handbook/README.md).
