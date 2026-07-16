# LangChain Agent Harness

Questo repository accompagna uno studente dalla prima chiamata a un modello fino a un
agent harness completo. Il progetto segue i meccanismi descritti nell'articolo
[The Anatomy of an Agent Harness](https://www.langchain.com/blog/the-anatomy-of-an-agent-harness):
prompt di sistema, strumenti, filesystem, esecuzione in sandbox, memoria, gestione del
contesto, pianificazione, subagenti, middleware, approvazione umana e verifica.

## Struttura

- `src/agent_harness`: applicazione finale (CLI, control plane FastAPI, runner, tool,
  sandbox, self-improvement).
- `client`: dashboard React (Control Center) che parla con il control plane via REST/SSE.
- `steps`: 20 snapshot incrementali. Ogni cartella contiene codice, guida e changelog.
- `notebooks`: 12 laboratori autonomi; 01–06 LangChain live, 07–12 offline standard-library.
- `skills`: istruzioni caricate su richiesta dall'agente (progressive disclosure).
- `memories`: memoria continua tra sessioni (`AGENTS.md`), sempre caricata nel prompt.
- `evals`: eval set versionato (`cases.json`) usato dal loop di self-improvement.
- `docker`: Dockerfile dell'immagine sandbox in cui gira `docker_exec`.
- `docs`: approfondimenti architetturali (mappa componenti, architettura, self-improvement).
- `workspace`: unica directory condivisa con il container Docker.
- `state`: checkpoint SQLite locali, trace, valutazioni e versioni di config.
- `tests`: test offline, senza consumo di token.

La matrice completa tra articolo e implementazione si trova in
[`docs/HARNESS_COMPONENTS.md`](docs/HARNESS_COMPONENTS.md); il diagramma dei componenti
in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).
La spiegazione didattica end-to-end è in
[`docs/GUIDA_DIDATTICA_COMPLETA.md`](docs/GUIDA_DIDATTICA_COMPLETA.md); la copertura
feature → step → notebook → test in
[`docs/MATRICE_COPERTURA_DIDATTICA.md`](docs/MATRICE_COPERTURA_DIDATTICA.md).

## Avvio rapido

Prerequisiti: Python 3.11 o successivo, `uv` e Docker Desktop.

```bash
cp .env.example .env
# Inserire OPENAI_API_KEY in .env
uv sync --extra dev
make sandbox-image
uv run harness doctor
uv run harness chat
```

CLI disponibile (`uv run harness <comando>`):

- `chat` — REPL interattiva, stesso `thread_id` persistente tra i messaggi.
- `run "<obiettivo>"` — esecuzione singola non interattiva.
- `improve --since 100` — genera una proposta di miglioramento dagli ultimi N run (propose-only, va valutata/promossa dal Control Center).
- `doctor` — verifica prerequisiti (`OPENAI_API_KEY`, workspace, Docker, immagine sandbox) senza chiamare il modello.

### Control Center React

Il client dashboard vive in `client/` e usa il control plane FastAPI reale. Sessioni,
messaggi, run, trace e usage sono persistiti in `state/control.sqlite`. Ogni conversazione
ha un workspace isolato sotto `state/sessions/<thread_id>/workspace`; upload e artefatti
non vengono condivisi tra thread.

```bash
# Terminale 1
uv run harness-api

# Terminale 2
cd client
npm install
npm run dev
```

Apri `http://127.0.0.1:5173` (oppure `make run`, che avvia API e client insieme).

**Conversazione.** Chat con streaming del delta del modello, tool, skills, richieste
di approvazione e token rate via SSE. Allegati caricabili da due punti (composer del
messaggio o tab File dell'inspector); immagini e artefatti prodotti dall'agente nel
workspace vengono renderizzati inline nella risposta, non solo linkati. Durante un run
il tasto invio diventa Stop; lo stato sandbox (autonoma o con approvazione) si cambia
cliccando l'etichetta accanto ad "Allega", senza lasciare la chat.

**Trace & Timeline.** Il tab Trace dell'inspector mostra l'azione corrente del run in
diretta (azione, durata, tool in esecuzione), visibile anche a inspector chiuso. La
vista **Traces**, separata, è una cronologia cross-run: elenco run con stato e durata,
e per il run selezionato una timeline a cascata di ogni tool call con argomenti/output
espandibili.

**File, Capabilities, Sandbox.** Gli altri tab dell'inspector: File elenca gli allegati
della sessione con download/cancellazione; Capabilities mostra skill e tool usati nel
run corrente; Sandbox mostra lo stato del container Docker effimero della sessione
(immagine, rete, limiti risorse, comando `docker_exec` in corso) con pulsante di stop.

**Skills.** Gestione completa da UI: creazione (nome, descrizione, corpo Markdown),
editor inline, badge di conformità/errori di validazione, cancellazione. Le modifiche
valgono dal run successivo. Meccanismo di progressive disclosure descritto in
[`docs/HARNESS_COMPONENTS.md`](docs/HARNESS_COMPONENTS.md).

**Triggers (Loop 3).** Run autonomi innescati da cron o webhook. Cron con preset
comuni pronti al click; webhook con token dedicato e comando `curl` già pronto da
copiare; test manuale, enable/disable, cancellazione. Il payload del webhook è sempre
trattato come dato non attendibile, mai come istruzione.

**Impostazioni.** Pannello di sola lettura sulla configurazione runtime attiva (modello,
finestra di contesto, stato sandbox, soglia rubric, scheduler trigger); la modifica
avviene via `.env` e richiede riavvio dell'API.

### Self-improvement controllato

Vista **Miglioramenti** implementa ciclo completo:

1. aggrega ultimi run terminali e trace correlati;
2. genera proposta entro whitelist;
3. confronta baseline e candidato su `evals/cases.json`;
4. separa check output, completion protocollo e feedback grader;
5. blocca regressioni, aumento eccessivo di token/latenza e reward hacking;
6. attribuisce run baseline/canary e applica un gate live con metriche in tempo reale
   (success/failure rate, score grader, token e latenza medi, con delta rispetto alla
   baseline), polling ogni 15 secondi finché una canary è attiva;
7. abilita promotion versionata al 100%;
8. consente rollback a qualunque config precedente da uno storico versioni salvate.

Rubric e soglia restano congelate. Evaluation usa chiamate modello reali solo dopo azione
esplicita. Dettagli e formule del gate: [`docs/SELF_IMPROVEMENT.md`](docs/SELF_IMPROVEMENT.md).

Esecuzione da CLI, alternativa al Control Center:

```bash
uv run harness run "Analizza i file nel workspace e crea report.md"
uv run harness improve --since 100
```

### Scala dei modelli

Il router sceglie fra tre gradini di costo crescente. Modello e reasoning effort salgono
insieme, perché un modello caro che ragiona poco paga il prezzo alto senza comprarne il
beneficio, e la coppia inversa spende reasoning su un modello che non lo sfrutta.

| Gradino | Modello | Reasoning | $/MTok input | $/MTok output |
|---|---|---|---|---|
| basso | `gpt-5.6-luna` | `low` | 1 | 6 |
| medio | `gpt-5.6-terra` | `medium` | 2,50 | 15 |
| alto | `gpt-5.6-sol` | `high` | 5 | 30 |

**Il router non prevede la difficoltà: la misura.** Ogni obiettivo parte dal gradino basso. Se
l'iterazione fallisce nettamente — il grader dà meno di `HARNESS_ESCALATION_THRESHOLD`, oppure
la verifica nella sandbox non riesce — la continuazione riparte un gradino sopra. Non ci sono
liste di parole chiave, quindi nessuna lingua è privilegiata: `analyze the csv file` e
`analizza il csv` si comportano allo stesso modo. E non si paga il modello caro per una
richiesta che quello economico avrebbe risolto, perché prima gli si lascia provare.

Le soglie sono **due**, perché le domande sono due:

| Soglia | Default | Domanda | Se non è soddisfatta |
|---|---|---|---|
| `HARNESS_RUBRIC_THRESHOLD` | 0,70 | L'obiettivo è raggiunto? | L'agente riprova |
| `HARNESS_ESCALATION_THRESHOLD` | 0,50 | Questo gradino ce la fa? | Il router sale di un gradino |

Fra le due, l'agente riprova **con lo stesso modello**: un secondo tentativo economico invece di
uno caro. Misurato sull'eval set: tre risposte corrette su sedici prendono fra 0,61 e 0,67, e
salire su ognuna significherebbe comprare il modello caro per un lavoro già fatto bene.

Costa un'iterazione in più sui compiti difficili. Il router precedente costava cinque volte
tanto su quelli facili che contenevano la parola sbagliata.

L'escalation vale per un obiettivo, non per la sessione: il messaggio successivo riparte dal
basso. Il pulsante nel composer fissa un gradino e spegne l'automatismo; un marcatore
`[Modello: alto]` scritto a mano nel testo scavalca anche quello.

Il grader a rubrica, il subagent revisore e il ricercatore non arrivano mai al gradino alto: il
primo gira una volta per iterazione, l'ultimo a ogni ricerca. All'alto ci arriva soltanto
l'agente principale.

Modelli, reasoning effort e prezzi si configurano da `.env`: `OPENAI_MODEL_LOW|MID|HIGH`,
`OPENAI_EFFORT_LOW|MID|HIGH`, `OPENAI_PRICE_IN|OUT_LOW|MID|HIGH`.

### Valutare prima di fidarsi

```bash
uv run harness eval --repeat 3            # ogni caso tre volte: un caso che passa 2/3 è instabile
uv run python evals/calibrate_grader.py   # il grader separa le risposte buone dalle cattive?
```

Il secondo comando è il prerequisito del primo. L'escalation del router si regge sul grader: se
il grader non discrimina, l'escalation eredita il rumore. Il criterio è `max(cattive) <
min(buone)`, e lo script esce con codice diverso da zero se le due nuvole si sovrappongono.

## Capacità dell'agente

- **Filesystem confinato**: lettura/scrittura solo dentro `workspace`, nessun path
  fuori dal confine.
- **Esecuzione codice**: `docker_exec` in sandbox effimera (vedi Sicurezza).
- **Lettura web**: `browser_read` con difese SSRF (solo HTTP/HTTPS, blocco IP privati/
  loopback, limite dimensione risposta).
- **Ricerca web**: strumento di ricerca opzionale per conoscenza recente.
- **MCP**: integrazione con server Model Context Protocol esterni, multi-server.
- **Subagenti isolati**: ricercatore e revisore con contesto proprio, non inquinano
  quello del coordinatore.
- **Model routing**: sceglie automaticamente modello economico o forte in base al compito.
- **Pianificazione**: `workspace/plan.md` più todo middleware per lavori lunghi.
- **Auto-verifica**: tool `verify_workspace` e grader a rubric prima di dichiarare
  un obiettivo completato.
- **Memoria continua**: `memories/AGENTS.md` caricato sempre, persiste tra sessioni.
- **Skills**: procedure caricate solo su richiesta (progressive disclosure), gestibili
  da UI (vedi sopra).

Mappa completa articolo → implementazione: [`docs/HARNESS_COMPONENTS.md`](docs/HARNESS_COMPONENTS.md).

## Sicurezza

Il tool `docker_exec` non esegue comandi sulla macchina host. Ogni chiamata crea un
container effimero con:

- rete disabilitata;
- filesystem root in sola lettura;
- capability Linux rimosse;
- limite di memoria, CPU, processi e tempo;
- mount in scrittura della sola cartella `workspace`;
- approvazione umana prima dell'esecuzione, quando abilitata.

L'immagine (`docker/sandbox.Dockerfile`) contiene Python, Git, jq, poppler-utils,
Node/npm con Playwright e Chromium già scaricati a build time (cache npm seminata e
forzata offline, così `npm install` nei progetti dell'agente non dipende dalla rete
a runtime), e i pacchetti Python più usati dall'agente: pandas, pillow, pypdf,
reportlab, python-docx/pptx, weasyprint, beautifulsoup4/lxml, pytest, ruff. Viene
costruita con:

```bash
make sandbox-image
```

Docker riduce il rischio ma non costituisce da solo un confine perfetto in ambienti
ostili. Non montare socket Docker, home directory o segreti nel container. Il backend
shell locale non viene usato dal progetto finale.

## Comandi

```bash
make install    # dipendenze Python + client React
make test       # test offline
make lint       # analisi statica
make format     # ruff format + fix automatico
make notebooks       # compila 01–12 ed esegue davvero gli offline 07–12
make notebooks-live  # esecuzione end-to-end con OPENAI_API_KEY
make sandbox-image # immagine Docker riproducibile
make run        # API + Control Center insieme
make chat       # chat interattiva CLI
make smoke      # run singolo di verifica end-to-end
```

## Percorso consigliato

1. Seguire le cartelle `steps` in ordine, dallo `00` al `19` (20 step totali).
2. Ricostruire manualmente ogni avanzamento usando `GUIDA.md`.
3. Aprire i notebook 01–06 per LangChain live e 07–12 per governance offline.
4. Leggere `src/agent_harness` per vedere come i componenti vengono assemblati.

Lo step 13 introduce il loop engineering (trigger cron/webhook e hill-climbing),
descritto in [*The Art of Loop Engineering*](https://www.langchain.com/blog/the-art-of-loop-engineering)
e mappato in [`docs/HARNESS_COMPONENTS.md`](docs/HARNESS_COMPONENTS.md).
Gli step 14–19 aggiungono provider-neutral runtime, budget, durabilità, governance subagenti,
evidence contract, delivery gate e Control Center completo.

## Tracing

Per inviare le tracce a LangSmith:

```dotenv
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=...
LANGSMITH_PROJECT=langchain-agent-harness
```

Nessuna chiave viene salvata nel codice o stampata nei log.
