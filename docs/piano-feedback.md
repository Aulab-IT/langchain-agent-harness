# Analisi dello stato attuale e piano a fasi

Documento di lavoro che risponde ai feedback raccolti sull'harness (Agent Studio). È diviso
in tre parti: una fotografia dell'architettura, le risposte alle domande poste, e un piano
di intervento a fasi con criteri di uscita espliciti.

---

## 1. Fotografia del sistema

**Backend** (`src/agent_harness/`)

- `server.py` — API FastAPI, `RunManager` che esegue un run per volta per sessione
  (409 se la sessione è occupata), streaming eventi via SSE con polling sulla tabella
  `events` ogni 250 ms.
- `factory.py` — costruisce il graph con `create_deep_agent` (deepagents): due modelli
  OpenAI (`gpt-5.4-mini` / `gpt-5.5`), tre middleware (router modello, audit,
  limite tool call), due subagent (`researcher`, `reviewer`), interrupt HITL su
  `docker_exec`, skills montate da `/skills`, memoria da `/memories/AGENTS.md`.
- `control_store.py` — SQLite (`state/control.sqlite`) per sessioni, messaggi, run,
  eventi, trigger. Ogni sessione ha una radice isolata in
  `state/sessions/<uuid>/{workspace,memories,skills}`.
- `sandbox.py` — un container Docker per sessione, con reaper per inattività.
- `runner.py` — ciclo di continuazione (max 3 iterazioni) con grader a rubrica.
- `improve.py` / `canary.py` / `promotion.py` / `evaluation.py` — loop di
  auto-miglioramento propose-only con gate su `evals/cases.json`.

**Frontend** (`client/src/`) — React, hook unico `useHarnessSession` che tiene runtime,
sessione, run, eventi, e deriva `skillItems` / `toolItems` per l'inspector.

---

## 2. Risposte alle domande poste

### 2.1 Come viene gestita la memoria `AGENTS.md`?

Il flusso reale, oggi, è questo:

1. Esiste un file sorgente unico, `memories/AGENTS.md` nella root del progetto (16 righe:
   preferenze operative + una sezione "Apprendimenti" che invita l'agente ad aggiornarla).
2. A ogni run, `ControlStore.prepare_session_root()` **copia** quel file in
   `state/sessions/<session_id>/memories/AGENTS.md`. Se il sorgente non esiste, ne crea uno
   stub con la sola intestazione.
3. `create_deep_agent(..., memory=["/memories/AGENTS.md"])` inietta quel contenuto nel
   contesto a ogni turno; i permessi filesystem concedono lettura **e scrittura** su
   `/memories/**`.

Ne discendono tre conseguenze non ovvie:

- **La memoria è per-sessione, non globale.** Ogni sessione parte da una copia del
  template. Ciò che l'agente impara nella sessione A è invisibile alla sessione B.
- **Gli apprendimenti sono volatili.** Non esiste alcuna risincronizzazione dalla sessione
  verso `memories/AGENTS.md`, e `delete_session()` fa `rmtree` della radice: cancellando la
  sessione si cancellano gli apprendimenti. La sezione "Apprendimenti" promette una
  durabilità che il codice non implementa.
- **La copia avviene a ogni run, non solo alla creazione.** `prepare_session_root` è
  invocata all'inizio di ogni `_execute`. Per le skills c'è un `rmtree` esplicito prima
  della ricopia (quindi si rigenerano da zero), mentre per `AGENTS.md` viene usato
  `shutil.copy2` senza guardia: **ogni nuovo run sovrascrive la memoria di sessione con il
  template globale**, perdendo quanto l'agente aveva scritto nel run precedente. Questo è
  un bug, non una scelta di design.

Il pannello Contesto (`_build_context`) legge invece il file di sessione, quindi mostra
correttamente ciò che l'agente vede — ma solo fino al run successivo.

### 2.2 Come funziona il multi-model, e come migliorarlo?

Oggi la selezione del modello vive interamente in `middleware.py::build_model_router`, 20
righe:

```python
last_text = str(messages[-1].content).casefold() if messages else ""
complex_hint = any(word in last_text for word in ("complesso", "architettura", ...))
selected = strong_model if len(messages) > 24 or complex_hint else default_model
```

Oltre a questo, il modello forte è cablato in altri tre punti: il grader a rubrica
(`RubricGrader.from_chat_model(strong_model, ...)`), il subagent `reviewer`, e il giudice
del loop di miglioramento (`build_strong_model`). Il subagent `researcher` usa il modello
default. I `reasoning_effort` sono fissi (`low` per il default, `medium` per il forte).

I problemi concreti:

1. **Il router legge l'ultimo messaggio, che spesso è un `ToolMessage`.** L'output di un
   tool che contiene la parola "refactor" o "architettura" fa scattare il modello forte.
   La decisione dovrebbe basarsi sull'ultimo messaggio *umano*, non sull'ultimo messaggio.
2. **La soglia `len(messages) > 24` è un interruttore a senso unico.** Superate 24 voci,
   ogni turno successivo usa il modello forte fino alla fine della sessione: il costo
   esplode proprio nelle conversazioni lunghe, dove servirebbe il contrario.
3. **Cambiare modello a metà conversazione invalida il prompt caching**, che è la leva di
   costo più importante su prompt di sistema lunghi.
4. **L'euristica è in italiano e non configurabile**: una richiesta complessa in inglese
   non la attiva.
5. **La UI mente.** `ChatMessage` mostra `runtime.model` (il modello *default*) su ogni
   messaggio dell'agente, anche quando il router ha scelto quello forte. Non c'è alcun
   evento che registri quale modello ha risposto.
6. **Nessun controllo utente**: non si può forzare un modello per una sessione o per un
   singolo messaggio, né vedere il costo per modello.

Direzione consigliata: rendere la scelta **esplicita, osservabile e correggibile** —
un evento `model.selected` per turno, il badge in chat che riflette il modello reale, una
selezione a tre livelli (override di sessione → override di messaggio → router automatico),
e un router che decide sull'ultimo turno umano con isteresi anziché con una soglia
monotona.

### 2.3 Cosa succede con due sessioni attive contemporaneamente? Sono isolate?

**Sono isolate a livello logico, ma non sono al riparo da contese a livello di storage.**

Cosa è isolato correttamente:

- Filesystem: radice per sessione (`state/sessions/<uuid>/`), workspace, memoria e copia
  delle skill distinte.
- Esecuzione: un container Docker per sessione (`session_sandbox_manager`), con reaper
  per inattività.
- Stato del graph: il checkpointer LangGraph usa `thread_id = session_id`, quindi due
  sessioni non si vedono i messaggi.
- Concorrenza applicativa: `RunManager.start()` prende un lock e rifiuta con 409 se la
  sessione ha già un run non terminale. Due run sulla *stessa* sessione sono impossibili;
  due run su sessioni diverse girano come task asyncio concorrenti.

Cosa invece è condiviso e non protetto:

- **`state/control.sqlite`** — una sola connessione, serializzata da un `threading.RLock`,
  **senza `PRAGMA journal_mode=WAL`**. Peggio: le chiamate sono sincrone e bloccanti
  dentro handler `async`, quindi la scrittura di un evento di una sessione blocca l'event
  loop (e quindi lo stream SSE) dell'altra.
- **`state/checkpoints.sqlite`** — ogni `build_harness` apre il proprio
  `AsyncSqliteSaver`. Due run concorrenti significano due connessioni in scrittura sullo
  stesso file, sempre senza WAL: sotto carico ci si aspetta `database is locked`
  (timeout SQLite di default 5 s).
- **`state/audit.jsonl`** — protetto da un lock di processo, quindi corretto, ma un punto
  di serializzazione.
- **`skills/` sull'host** — se una sessione crea o installa una skill mentre un'altra sta
  facendo `prepare_session_root` (che fa `rmtree` + `copytree`), la seconda può leggere un
  albero a metà. La finestra è stretta ma reale.
- **`state/harness_overrides.toml` e `canary.json`** — letti a ogni `build_harness`;
  una promozione durante un run attivo cambia la config sotto i piedi al run successivo,
  non a quello in corso (comportamento accettabile, ma non documentato).

Non ci sono perdite di dati tra sessioni; ci sono contese e stalli. Il rimedio è
economico: WAL + `busy_timeout` sulle due basi, esecuzione delle chiamate SQLite in
thread pool, e un lock sulla directory `skills/` durante la preparazione della radice.

---

## 3. Analisi puntuale degli altri feedback

### 3.1 Messaggi intermedi durante l'esecuzione

Oggi in chat, mentre l'agente lavora, si vede: un blocco di testo che concatena **tutti**
gli `assistant.delta` del run, e una riga `ThinkingTrace` con l'azione corrente. Tutto il
resto (tool call, argomenti, output, subagent, grader) esiste solo come evento e va cercato
nell'inspector, tab Trace.

Tre difetti specifici:

- `liveText` in `ChatPanel` unisce i delta di **tutte** le iterazioni di continuazione:
  se il runner fa un secondo giro, il testo del primo resta incollato davanti al secondo.
- Le tool call non compaiono mai nel flusso della conversazione, quindi l'utente non ha
  modo di capire *perché* l'agente sta impiegando tempo se non cambiando pannello.
- I subagent (`researcher`, `reviewer`) non sono distinguibili: i loro eventi tool
  arrivano indistinti da quelli dell'agente principale.

### 3.2 Spiegazione del comando da approvare

`ApprovalDialog` mostra il comando grezzo dentro un `<pre>` più un avviso se c'è accesso
rete. Il payload lato server (`approval()` in `server.py`) è già ridotto a
`{action, description, command, network}`: la `description` è una costante di due varianti.

Manca qualsiasi lettura di *cosa fa* il comando. Nota che la spiegazione va prodotta senza
introdurre latenza in un percorso bloccante (il run è sospeso in attesa dell'utente) e
senza dare al modello l'ultima parola su un controllo di sicurezza: la scelta giusta è un
classificatore statico del comando (installa pacchetti, scrive file, cancella, apre rete,
esegue test…) con evidenziazione dei percorsi toccati, e — solo come complemento — una
frase generata dal modello, chiaramente marcata come tale.

### 3.3 Tab "Capabilities" dell'inspector

Il tab elenca **tutte** le skill installate e una lista di tool hardcoded in
`server.py::_tools()`, indipendentemente dal fatto che siano stati usati. Peggio, quella
lista è sbagliata: contiene `"mcp:local_harness"`, che non è il nome di nessun tool
(i tool MCP reali si chiamano `count_text`, `harness_glossary`, `skill_list`,
`skill_read`, `skill_create`, `skill_write_file`, `skill_install`), e omette tutti i tool
di filesystem, todo e subagent che deepagents inietta nel graph. Di conseguenza
`observedTools` in `useHarnessSession` finisce per fondere due insiemi che non si
sovrappongono, e lo stato "pronto" è mostrato per tool che non esistono.

Il feedback è centrato: il tab deve diventare il **registro di ciò che è successo in questa
sessione** — quali skill sono state effettivamente lette, quali tool chiamati, quante volte,
con quale esito e quanto tempo. Tutti i dati necessari sono già negli eventi
(`tool.started` / `tool.completed` / `tool.failed` con `elapsed_ms`, e `skill` derivato dal
path in `AuditMiddleware._emit`).

### 3.4 Menu Tools speculare a Skills

`SkillsView` (622 righe) offre lista, editor, file di risorsa, install da git/URL/registry,
log installazioni. Per i tool non esiste nulla: nessun endpoint che ne esponga nome,
descrizione e schema degli argomenti, nessuna vista.

Il pezzo mancante lato backend è banale: `Harness.tools` è già una `list[BaseTool]`, quindi
`name`, `description` e `args_schema` sono disponibili. Serve però costruirla fuori dal
contesto di un run (oggi `build_tools` è chiamata solo dentro `build_harness`).

### 3.5 skill-creator

Non presente in `skills/` (ci sono `gmail-cli-oauth`, `keynote-generator`,
`project-writing`, `research`). Oggi, quando l'agente deve creare una skill, usa il tool
MCP `skill_create` che scrive un `SKILL.md` con frontmatter minimale e nessuna guida sul
contenuto.

L'infrastruttura per installarla esiste già: `install_skill(source="git", ...)` con
`subdir`, con clone `--depth 1` e guardie SSRF. Va (a) installata come skill di prima
classe, (b) resa *obbligatoria per convenzione* nel system prompt quando l'obiettivo è
creare o modificare una skill, e (c) esposta con un pulsante dedicato in `SkillsView`.

### 3.6 Invocazione skill con `/`

`ChatComposer` è una `textarea` senza alcuna gestione di `/`. Le skill sono già note al
client (`runtime.skills`). Serve: rilevamento del `/` a inizio riga, popup di autocomplete
filtrato, navigazione da tastiera, inserimento di un token, evidenziazione del token come
"chip", e — lato invio — la traduzione del token in un'istruzione esplicita per l'agente.

Attenzione a un punto non ovvio: l'agente **non ha un meccanismo di invocazione diretta**
delle skill. Le skill sono documenti che lui sceglie di leggere. Una `/skill` selezionata
dall'utente deve quindi diventare un vincolo nel prompt ("usa la skill X, leggila prima di
procedere"), non una chiamata di funzione. Va detto chiaramente nell'interfaccia, altrimenti
si crea l'aspettativa di un comando deterministico che il sistema non garantisce.

### 3.7 Eval set

`evals/cases.json` contiene **tre** casi: una moltiplicazione, la scrittura di un file con
una riga fissa, la somma di cinque interi da un JSON. I check disponibili sono solo
`answer_contains`, `file_exists`, `file_contains`.

Questo eval set è troppo debole per fare da gate a una promozione di configurazione: non
copre ricerca web, uso di skill, richieste ambigue, task multi-turno, casi che devono
*fallire* o rifiutare, il percorso di approvazione, né la qualità della prosa. Un
`system_prompt_addendum` peggiorativo passerebbe il gate senza difficoltà. Serve
ampliamento dei casi **e** ampliamento dei tipi di check (giudizio a rubrica, assenza di
una stringa, numero massimo di tool call, esito atteso di rifiuto).

### 3.8 Selettore cron

In `TriggersView` il cron è un campo di testo libero con default `*/5 * * * *`.
Lato server, `cron_matches` valuta l'espressione contro `datetime.now(UTC)`.

Due problemi distinti, e il secondo è più grave del primo:

- **Usabilità**: nessun preset, nessuna traduzione in linguaggio naturale, nessuna anteprima
  delle prossime esecuzioni. L'utente scrive una stringa e spera.
- **Fuso orario**: lo scheduler ragiona in UTC e non lo dice da nessuna parte. Un utente
  italiano che imposta `0 9 * * *` per "ogni mattina alle 9" ottiene le 10:00 in inverno e
  le 11:00 in estate. Non c'è alcun campo timezone né nella tabella `triggers` né nella UI.

Nota minore: `TriggerScheduler._fired_minutes` cresce senza limite (una voce per trigger,
mai ripulita) e i trigger sono valutati a tick di 30 s, quindi un cron al minuto può
saltare un'esecuzione se il tick cade male.

### 3.9 Anteprima file in chat

`ChatMessage` rende gli allegati come `<a download>`. L'endpoint
`GET /api/sessions/{id}/files/{path}` risponde con `FileResponse(target, filename=...)`,
che impone `Content-Disposition: attachment` — quindi oggi l'anteprima è impossibile anche
volendo, lato client.

Qui la sicurezza detta il design, perché **questi file sono prodotti dall'agente o caricati
dall'utente, e `_ALLOWED_UPLOADS` include `.html` e `.svg`**. Servirli inline sull'origine
dell'API significa XSS stored. La linea da tenere:

- Immagini raster (`png`, `jpg`, `jpeg`, `webp`, `gif`) → inline, con
  `X-Content-Type-Options: nosniff` e Content-Type dedotto dall'estensione whitelistata,
  mai dal client.
- PDF → inline in `<iframe sandbox>`, sapendo che il visualizzatore PDF del browser è
  comunque una superficie d'attacco: `sandbox` senza `allow-scripts`.
- `svg` e `html` → **mai** inline. Download, oppure rendering come testo sorgente.
- `pptx`, `xlsx`, `docx` → nessuna anteprima nativa nel browser. O si accetta un
  riquadro con metadati (nome, dimensione, numero di slide/fogli estratto server-side), o
  si genera una miniatura via conversione fuori processo. La seconda opzione è un progetto
  a sé: fuori dal perimetro delle fasi qui sotto.

### 3.10 Loops (articolo Anthropic)

L'articolo distingue quattro pattern: turn-based, goal-based (con valutatore e limite di
turni), time-based (`/loop`, `/schedule`) e proattivi. Le raccomandazioni operative sono:
codificare la verifica in skill con criteri quantitativi, definire condizioni d'uscita
deterministiche, instradare i modelli per costo, monitorare il consumo di token.

Confronto con l'harness: il **goal-based loop c'è già** ed è la parte migliore del sistema
(`GoalRunner` con `RubricGrader`, `harness_max_continuations`, `has_successful_verification`).
Il **time-based loop c'è a metà**: i trigger cron esistono ma sono disattivati per default
(`harness_enable_triggers: bool = False`) e non hanno visibilità sugli esiti.

I due innesti mancanti, in ordine di valore:

1. **Criteri di uscita per-trigger.** Oggi un trigger porta solo un `goal_template`; la
   rubrica di uscita è globale (`state/rubric.md`). Un loop ricorrente serio ha bisogno di
   una condizione di successo propria.
2. **Osservabilità del loop.** Non esiste una vista "questo trigger è girato N volte, M
   sono passate al grader, ecco il trend". Gli eventi ci sono tutti; manca l'aggregazione.

---

## 4. Piano a fasi

Ogni fase è pensata per essere rilasciabile da sola. L'ordine massimizza il rapporto tra
valore percepito e rischio: prima si smette di mentire all'utente, poi gli si dà più
informazione, poi più controllo.

### Fase 0 — Correggere ciò che è già sbagliato

Nessuna funzionalità nuova. Sono bug che rendono fuorviante ciò che l'interfaccia mostra e
che le fasi successive amplificherebbero.

1. `prepare_session_root` non deve sovrascrivere `memories/AGENTS.md` se il file di sessione
   esiste già (copiare solo alla creazione della radice).
2. `_tools()` deve derivare i nomi dai tool realmente costruiti, non da una lista letterale.
   Estrarre la costruzione dei tool in modo che sia interrogabile fuori da un run.
3. `PRAGMA journal_mode=WAL` e `busy_timeout` su `control.sqlite` e `checkpoints.sqlite`.
4. `liveText` deve azzerarsi a ogni iterazione di continuazione (marcare i delta con
   l'indice di iterazione, o emettere un evento di confine).
5. Il badge modello in `ChatMessage` non deve dichiarare un modello che non ha risposto:
   finché non c'è l'evento `model.selected` (Fase 3), rimuoverlo o renderlo generico.

*Uscita*: i test esistenti passano; una sessione con due run consecutivi conserva la
memoria scritta dall'agente; il tab Tools non elenca tool inesistenti.

### Fase 1 — Osservabilità del run

Il tema è: durante l'esecuzione l'utente deve capire cosa sta succedendo senza cambiare
pannello, e deve poter approvare un comando avendolo compreso.

1. **Passi intermedi in chat.** Rendere le tool call come righe compatte nel flusso della
   conversazione (nome, argomento principale, durata, esito), collassate per default,
   espandibili. Attribuire i passi al subagent che li ha eseguiti quando applicabile —
   richiede di propagare l'identità del subagent nell'evento `tool.*`.
2. **Approvazione spiegata.** Classificatore statico del comando lato server, allegato al
   payload `approval.requested`: categoria (installazione / scrittura / cancellazione /
   rete / lettura / esecuzione test), percorsi toccati, e i vincoli già attivi (nessuna
   rete salvo richiesta, 512 MB, 1 core). La spiegazione in linguaggio naturale generata
   dal modello, se la si vuole, arriva come campo separato e visibilmente etichettato.
3. **Tab "Attività di sessione"** al posto di "Capabilities": elenco delle skill lette e
   dei tool chiamati **in questa sessione**, con conteggio invocazioni, tempo totale,
   ultimo esito. Deriva interamente dagli eventi già presenti.

*Uscita*: un run che installa una libreria e scrive un file è leggibile dalla sola chat;
il dialogo di approvazione dice cosa fa il comando prima di chiedere il consenso.

### Fase 2 — Superficie di controllo su skills e tools

1. **Endpoint `GET /api/tools`** con nome, descrizione, schema argomenti, origine
   (built-in / MCP / subagent) e stato di abilitazione.
2. **Vista Tools** speculare a `SkillsView`: lista, dettaglio, e — dove ha senso —
   interruttore di abilitazione per sessione. Attenzione: disabilitare `docker_exec`
   svuota di senso il grader di verifica; l'interfaccia deve dirlo.
3. **`/` in composer**: autocomplete sulle skill, navigazione da tastiera, chip evidenziato.
   La skill selezionata viene tradotta in un vincolo esplicito nel goal, e l'interfaccia
   spiega che è un suggerimento forte, non una chiamata di funzione.
4. **skill-creator**: installazione via `install_skill(source="git", subdir="skill-creator")`,
   regola nel system prompt che ne impone la lettura prima di creare o modificare una skill,
   e pulsante "Crea con skill-creator" in `SkillsView`.

*Uscita*: si può scoprire dall'interfaccia quali tool esistono e cosa fanno; digitare
`/research` propone la skill e la evidenzia; chiedere all'agente di creare una skill produce
un `SKILL.md` conforme allo standard.

### Fase 3 — Modelli espliciti e memoria durevole

1. **Router riscritto**: decisione sull'ultimo messaggio *umano*; soglia con isteresi al
   posto dell'interruttore monotono; parole chiave configurabili e bilingui; override di
   sessione e di singolo messaggio.
2. **Evento `model.selected`** per turno, con modello e motivo della scelta. Badge in chat
   e riga nella trace. Costo per modello nel pannello Contesto.
3. **Memoria**: decidere e implementare la semantica. Proposta: `memories/AGENTS.md` di
   progetto resta il *template* di sola lettura; gli apprendimenti di sessione vivono nel
   file di sessione e sopravvivono ai run (Fase 0); una promozione esplicita dall'interfaccia
   copia un apprendimento nel template globale. Nessuna promozione automatica: la memoria
   condivisa è un canale di prompt injection tra sessioni.

*Uscita*: il badge in chat dice il vero; l'utente può forzare il modello forte su un
messaggio; un apprendimento sopravvive a un secondo run e non attraversa le sessioni senza
consenso.

### Fase 4 — Anteprima file e tenuta sotto concorrenza

1. **Anteprima**: nuovo endpoint `GET .../files/{path}/preview` che serve inline **solo**
   le estensioni raster whitelistate e i PDF, con `nosniff` e Content-Type derivato
   dall'estensione. `svg` e `html` restano download. Componente di anteprima in
   `ChatMessage` con lightbox per le immagini e `<iframe sandbox>` per i PDF. Per i
   formati Office, riquadro con metadati.
2. **Concorrenza**: chiamate SQLite fuori dall'event loop; lock sulla preparazione di
   `skills/`; test di carico con due sessioni che scrivono eventi in parallelo; verifica
   che lo stream SSE di una sessione non si blocchi durante un run dell'altra.

*Uscita*: due sessioni con run simultanei non producono `database is locked` né stalli
nello streaming; un `.png` prodotto dall'agente si vede in chat; un `.html` prodotto
dall'agente non esegue script sull'origine dell'API.

### Fase 5 — Loop, trigger e valutazione

1. **Eval set**: portarlo da 3 a ~20 casi che coprano ricerca web, uso di skill, richieste
   ambigue, task che devono fallire o rifiutare, prosa valutata a rubrica. Aggiungere i tipi
   di check corrispondenti (`answer_not_contains`, `max_tool_calls`, `rubric`,
   `expect_refusal`). Questo è il prerequisito perché il gate di promozione della config
   significhi qualcosa.
2. **Cron usabile**: presets ("ogni giorno alle…", "ogni lunedì…"), traduzione
   dell'espressione in linguaggio naturale, anteprima delle prossime tre esecuzioni, e
   **campo timezone** (colonna in `triggers`, conversione in `cron_matches`). Il timezone è
   la parte non negoziabile: senza, il selettore resta sbagliato anche se diventa bello.
3. **Loop**: criterio di uscita per-trigger (rubrica propria accanto al `goal_template`) e
   vista di aggregazione degli esiti per trigger. Poi valutare se attivare i trigger per
   default, cosa che oggi non è prudente.

*Uscita*: un utente non tecnico crea un trigger giornaliero alle 9 del mattino ora italiana
e vede se le ultime esecuzioni hanno superato il criterio di successo.

---

## 5. Dipendenze tra le fasi

- La Fase 1 (spiegazione approvazione, tab attività) non dipende da nulla, ma il tab
  attività è molto più utile dopo il punto 2 della Fase 0 (lista tool corretta).
- La Fase 2 punto 1 (endpoint tools) è un prerequisito della vista Tools e riusa
  l'estrazione fatta in Fase 0.
- La Fase 3 punto 3 (memoria) dipende dalla correzione in Fase 0 punto 1: senza, ogni
  apprendimento viene distrutto al run successivo e non c'è nulla da promuovere.
- La Fase 5 punto 1 (eval set) andrebbe fatto **prima** di qualsiasi altra promozione di
  configurazione tramite il loop di miglioramento, perché oggi il gate non discrimina.
