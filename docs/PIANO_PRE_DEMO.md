# Analisi pre-demo e piano di intervento

**Data analisi:** 11 luglio 2026
**Scadenza:** demo di martedì 14 luglio 2026
**Ambito:** meccanismi dell'harness, context engineering (visibilità + lancio manuale),
loop engineering, MCP configurabile da impostazioni, gestione della memoria.
**Fuori ambito (per ora):** autenticazione, ruoli, multi-utente.

## Sintesi

La base è solida: 289 test tutti verdi, architettura pulita, sicurezza sandbox ben
pensata. Ma ci sono **tre moduli interi scritti, testati e mai collegati**
(`context_budget.py`, `durable.py`, `LiveUsageThrottle`), un bug che **rompe ogni run
se non si usa OpenAI**, la compaction del contesto che **avviene già oggi ma in modo
invisibile e con soglie non nostre**, MCP chiuso a un solo server hardcoded, e la
memoria che è gestita bene ma poco raccontata.

---

## 1. Bug, in ordine di gravità

1. **Ogni run pretende `OPENAI_API_KEY`, anche con provider Anthropic o locali** —
   `server.py:700`: `if not settings.openai_api_key: raise RuntimeError(...)` sta nel
   percorso di ogni esecuzione, mentre `factory.py` richiede correttamente le chiavi
   per-provider. Una config tutta Ollama o tutta Claude (che il README promette
   esplicitamente) fallisce sempre dal Control Center. Stesso vizio in `/api/status`:
   `"configured": bool(settings.openai_api_key)` (`server.py:952`), quindi la UI
   dichiara "non configurato" un setup Claude perfettamente valido. Fix da mezz'ora.

2. **Write amplification su `usage.live`** — ogni `assistant.delta` genera *due* INSERT
   nel control DB (`server.py:606-616`): è il problema da ~33k eventi/run documentato
   in `context_budget.py:285`. Il rimedio esiste già, è `LiveUsageThrottle`, scritto e
   testato apposta: **non è mai stato collegato**. Trenta minuti per agganciarlo in
   `RunManager._execute`.

3. **`context_budget.py` interamente scollegato** — `ContextBudgetManager`,
   `offload_tool_output`, `StructuredSummary`: nessun import fuori dai test. Quindi
   `HARNESS_CONTEXT_WINDOW`, `harness_context_warning_ratio` e
   `harness_context_compaction_ratio` restano metadati mai applicati, nonostante il
   docstring del modulo e il commento in `config.py:84-86` dichiarino il contrario.
   Dettagli al §2.

4. **Euristica di verifica solo in italiano** — `runner.py:38-51`:
   `requires_environment_verification` riconosce «crea, scrivi, modifica…» ma non
   «create, write, fix». Un goal in inglese salta il requisito di verifica in sandbox.
   Incoerente con la filosofia del router («nessuna lingua privilegiata»,
   `middleware.py`). Aggiungere i verbi inglesi o, meglio, delegare al grader.

5. **Verifica contaminata dai run precedenti** — `has_successful_verification`
   (`runner.py:54-60`) scandisce *tutta* la storia del thread: un `docker_exec` con
   `exit_code=0` di tre goal fa soddisfa la verifica del goal corrente. Va limitata ai
   messaggi successivi all'ultimo `HumanMessage`.

6. **Un server MCP rotto blocca tutti i run** — in `factory.py:395`
   `await _load_mcp_tools(...)` non ha try/except (il catalogo ce l'ha,
   `factory.py:198-202`; il build no). Oggi il server è interno e affidabile; il giorno
   in cui gli utenti configurano server esterni (§4) diventa il modo più facile per
   spaccare tutto.

7. **Trigger cron: scheduler spento di default e non attivabile da UI** —
   `harness_enable_triggers: bool = False` (`config.py:104`) e il flag non è in
   `FLAG_FIELDS` di `provider_settings.py`, quindi dalla UI non si accende. Trappola
   perfetta per la demo: crei il trigger cron dal Control Center, la preview mostra le
   prossime esecuzioni, e non scatta mai. I webhook invece funzionano sempre
   (l'endpoint non passa dallo scheduler).

8. **`_TOOL_CATALOG` mai invalidato** — cache globale (`factory.py:167`); disattivando
   browser/MCP dalle impostazioni il pannello tool mostra il catalogo vecchio fino al
   riavvio. Basta azzerarlo in `update_provider_settings`.

9. **`durable.py` scollegato** — run, approvazioni e user action vivono in
   `asyncio.Task`: un riavvio del backend perde tutto. È la Fase 3 del piano evolutivo,
   non un lavoro per martedì; ma per la demo: **non riavviare l'API con un run attivo**.

10. Minori: timeout approvazione 600 s → reject silenzioso; `_emit_usage_snapshot`
    ricalcola `compute_usage` su tutti i messaggi a ogni superstep (O(n²) sul run);
    `_persist_context` gira solo a run completato, quindi su cancel/crash
    `context.json` resta stale.

---

## 2. Context engineering — cosa succede davvero, come renderlo visibile e manuale

Scoperta importante: **la compaction avviene già oggi**, ma non nel nostro codice.
`create_deep_agent` inserisce di default `create_summarization_middleware(model,
backend)` (verificato in `deepagents/graph.py:801`): quando il contesto supera la
soglia *del profilo del modello*, i messaggi vecchi vengono riassunti con una chiamata
LLM e la storia integrale finisce in `/conversation_history/{thread_id}.md` nel
backend. Quindi:

- succede con soglie decise da deepagents, **non** con le nostre
  (`harness_context_*` ignorate);
- è **invisibile**: nessun evento, nessuna traccia in UI, nessuna voce di audit;
- non è lanciabile a mano;
- il nostro `context_budget.py` — che è proprio il pezzo «policy + azioni +
  osservabilità» — è pronto e scollegato.

### Nota sul valore «context 128k»

`harness_context_window` (`config.py:83`, default `128_000`) è la finestra di contesto
*dichiarata*: oggi serve solo alla barra della UI e a `/api/status`, nessun codice la
applica. Si cambia da `.env` (`HARNESS_CONTEXT_WINDOW=...`) con riavvio dell'API; non è
nella whitelist modificabile da UI. Il valore giusto è la finestra reale del modello in
uso (es. 400k gpt-5.6, 200k Claude, 32k–128k per i locali Ollama, dove sforare
significa errore del provider). È un valore unico globale mentre i tre gradini possono
avere finestre diverse: andrebbe legato al descriptor del modello (Fase 2 del piano
evolutivo). Con l'intervento §2c diventa un limite realmente applicato.

### Proposta (fattibile entro martedì)

**a. Visibilità.** Sottoclasse (o wrapper) del `SummarizationMiddleware` di deepagents
che emette `context.compaction.started` / `context.compaction.completed` con token
prima/dopo attraverso l'`event_callback` già esistente → SSE → voce nel Trace e badge
nel `ContextPanel`. In più, arricchire `usage.snapshot` con il `fill_ratio` calcolato
da `ContextBudgetManager.inspect()` (già pronto e testato) e colorare la barra contesto
della UI sulle soglie 70% / 80%. Così *si vede quando* il context engineering lavora.

**b. Lancio manuale.** Due leve, entrambe a basso costo:

- deepagents include già `SummarizationToolMiddleware`, che espone il tool
  `compact_conversation`: abilitarlo dà all'agente (e all'utente via prompt) la
  compattazione on-demand;
- endpoint `POST /api/sessions/{id}/context/compact` che apre il graph sul checkpoint
  della sessione, esegue la compaction e persiste → pulsante «Compatta contesto» nel
  `ContextPanel`, attivo quando la sessione non è in run.

**c. Soglie nostre — rivisto in fase di implementazione.** L'idea iniziale era passare
`trigger=("fraction", harness_context_compaction_ratio)` con la finestra da `Settings`.
Verificando il codice di deepagents è emerso che la soglia frazionale usa già la finestra
**reale del modello** (dal suo profilo, `max_input_tokens`), non un numero globale. Forzare
la nostra `HARNESS_CONTEXT_WINDOW` unica su tre modelli con finestre diverse sarebbe *peggio*.
Decisione finale: **non si sovrascrive** il trigger di deepagents. `HARNESS_CONTEXT_WINDOW`
resta il riferimento per la barra della UI e per il `fill_ratio` degli eventi; la compaction
automatica scatta sulla finestra vera del modello. Il `ContextMonitorMiddleware` rende
comunque visibile la pressione con le nostre soglie warning/compaction.

Sul destino di `context_budget.py`, raccomandazione: **tenerlo come layer di
telemetria e policy** (snapshot, fill ratio, decisione da mostrare in UI). L'osservabilità
live è ora fornita dal nuovo `context_monitor.py`; `LiveUsageThrottle` è stato collegato.
`OffloadedOutput`/`drop_reconstructible` restano utili come passo «economico» prima del
riassunto LLM, ma sono un raffinamento post-demo.

### Stato implementazione (aggiornato)

Tutti i punti realizzati su branch `feat/pre-demo-harness`:

- **Bug 1** chiave OpenAI → validazione per-provider (`server.py`, `provider_settings.validate_overrides`).
- **Bug 2** `LiveUsageThrottle` collegato a `usage.live`.
- **Bug 4/5** verbi di verifica IT+EN, verifica limitata al turno corrente.
- **Bug 6** loader MCP resiliente per-server con evento `mcp.server.failed`.
- **Bug 7** toggle scheduler da UI (`PUT /api/settings/triggers`, start/stop a caldo) + evento `trigger.skipped`.
- **Bug 8** invalidazione `_TOOL_CATALOG` al cambio impostazioni.
- **§2a** `ContextMonitorMiddleware`: eventi `context.snapshot` (al cambio pressione) e `context.compaction.detected`; barra colorata.
- **§2b** compaction manuale: tool `compact_conversation` abilitato + `POST /api/sessions/{id}/context/compact` + pulsante «Compatta» nel ContextPanel.
- **§4** `state/mcp.json` (formato `mcpServers`, `${VAR}`), API `GET/PUT /api/settings/mcp` + `/status`, sezione «Server MCP» nelle Impostazioni.
- **§5** cap dimensione memoria (`HARNESS_MEMORY_MAX_CHARS`) con evento `memory.truncated`; token della memoria nel pannello; nota promozione-overwrite documentata.

---

## 3. Loop engineering

La parte trigger è ben progettata: cron timezone-aware con gestione DST corretta
(`triggers.py:53-78`), anti-doppio-fire con chiave minuto in UTC, payload webhook
sempre trattato come dato non attendibile, token con `secrets.compare_digest`, skip
pulito se la sessione è occupata, `success_criteria` iniettato come criterio d'uscita
del loop. Il ciclo di self-improvement (improve → eval → canary gate → promote →
rollback) è completo e non ha bisogno di interventi per la demo.

Gap in ottica production:

- **Nessun catch-up**: se l'API era giù nel minuto del cron, quel fire è perso per
  sempre — non esiste un `next_due` persistito. Per production serve persistere
  l'ultima esecuzione dovuta e recuperare al boot.
- **Skip invisibile**: «sessione occupata» finisce solo nel log (`server.py:869`);
  merita un evento `trigger.skipped` visibile nella vista Triggers.
- **Nessun freno**: un trigger `* * * * *` con un goal che fallisce sempre brucia token
  per sempre. Servono un cap di fire/ora e un auto-disable dopo N fallimenti
  consecutivi.
- Il toggle dello scheduler da UI (bug 7) è il pezzo che sblocca la demo.

---

## 4. MCP configurabile dalle impostazioni

Oggi: un solo server hardcoded (`local_harness`, stdio, `factory.py:100-120`) e un flag
on/off globale. Design proposto, nel formato standard usato da Claude Desktop/Cursor:

- **File `state/mcp.json`**, formato `mcpServers`:

  ```json
  {
    "mcpServers": {
      "github": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-github"],
        "env": { "GITHUB_TOKEN": "${GITHUB_TOKEN}" }
      },
      "linear": { "url": "https://mcp.linear.app/sse", "transport": "sse" }
    }
  }
  ```

  `MultiServerMCPClient` accetta già più server e i transport stdio/sse/
  streamable-http: il loader deve solo fare merge di `local_harness` + server utente.
  Supportare `${VAR}` espanso dall'ambiente, così i segreti non finiscono nel JSON.
- **Resilienza per-server**: `get_tools()` con timeout e try/except per server; un
  server che non parte genera un evento `mcp.server.failed` e il run prosegue senza i
  suoi tool (mai bloccare il run — vedi bug 6).
- **API**: `GET/PUT /api/settings/mcp` (JSON grezzo + validazione schema),
  `GET /api/settings/mcp/status` (per server: connesso, numero tool, ultimo errore).
  Il PUT invalida `_TOOL_CATALOG`.
- **UI**: sezione «Server MCP» in `SettingsView` — editor JSON monospace con
  validazione al salvataggio, riga di stato per server con lista tool espandibile.
- **Nota di sicurezza da scrivere in UI**: i server stdio girano *sull'host*, fuori
  dalla sandbox Docker. È il punto più delicato del progetto lato sicurezza; valutare
  in seguito `interrupt_on` opzionale per i tool MCP marcati sensibili.

---

## 5. Memoria — com'è gestita

È gestita, con il modello «file markdown stile AGENTS.md», su due livelli:

1. **Template globale** `memories/AGENTS.md` nel repo: il seme, modificabile da
   `GET/PUT /api/memory`.
2. **Copia per sessione** in `state/sessions/<id>/memories/AGENTS.md`, seminata *una
   sola volta* al primo run (`control_store.py:739-747`, mai ricopiata per non
   distruggere gli apprendimenti). deepagents la carica **sempre** nel prompt
   (`memory=["/memories/AGENTS.md"]` in `factory.py:504`) e l'agente ha permesso di
   scrittura su `/memories`, quindi può aggiornarla da solo.
3. **Promozione manuale** sessione → template (`POST .../memory/promote`), volutamente
   mai automatica: il commento in `server.py:1145-1149` spiega il perché
   (anti prompt-injection cross-sessione). C'è anche il `MemoryPanel` nell'inspector.

Il meccanismo è sano; è poco raccontato. Gap reali:

- (a) nessun limite di dimensione quando *l'agente* scrive la memoria — il cap 100k
  vale solo per la UI — e una memoria che cresce è un prompt che cresce a ogni run,
  per sempre;
- (b) i token della memoria sono già categorizzati «System & memoria» nel contesto, ma
  varrebbe la pena mostrarli esplicitamente nel MemoryPanel;
- (c) la promozione sovrascrive il template invece di fare merge — accettabile, ma da
  documentare.

---

## 6. Ottimizzazioni minori (post-demo)

- SSE: polling 0,25 s per stream aperto → ok per la demo; in futuro
  `asyncio.Condition`/notify al posto del polling.
- `compute_usage` O(n²) sul run (vedi bug 10).
- `_persist_context` anche su cancel (oggi solo a run completato; l'usage su cancel è
  già preservato).
- `session_events` senza paginazione.
- Invalidazione del catalogo tool al cambio impostazioni (bug 8).

---

## 7. Piano per martedì, in ordine

| # | Intervento | Stima |
|---|---|---|
| 1 | Fix chiave OpenAI hardcoded nel run + `configured` in `/api/status` (bug 1) | 30 min |
| 2 | Collegare `LiveUsageThrottle` a `usage.live` (bug 2) | 30 min |
| 3 | Eventi `context.compaction.*` + `fill_ratio` in `usage.snapshot` + soglie colorate nel ContextPanel (§2a) | ½ giornata |
| 4 | Compattazione manuale: tool `compact_conversation` + endpoint + pulsante (§2b) | ½ giornata |
| 5 | `mcp.json` + loader resiliente + sezione Settings (§4) | 1 giorno |
| 6 | Toggle scheduler trigger da UI + evento `trigger.skipped` (bug 7, §3) | 2 ore |
| 7 | Verbi inglesi in `requires_environment_verification` + verifica limitata al turno corrente (bug 4-5) | 1 ora |
| 8 | Prova generale: un run lungo che sfori la soglia di compaction, per mostrare l'evento dal vivo | — |

### Promemoria per il giorno della demo

- Non riavviare l'API con run attivi (durable non collegato).
- Docker Desktop acceso, immagine sandbox costruita (`make sandbox-image`).
- Se la demo usa provider non-OpenAI, il fix n. 1 è **obbligatorio**, non opzionale.
- `HARNESS_ENABLE_TRIGGERS=true` in `.env` se la demo mostra i trigger cron.
