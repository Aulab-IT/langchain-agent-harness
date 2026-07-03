# LangChain Agent Harness

Questo repository accompagna uno studente dalla prima chiamata a un modello fino a un
agent harness completo. Il progetto segue i meccanismi descritti nell'articolo
[The Anatomy of an Agent Harness](https://www.langchain.com/blog/the-anatomy-of-an-agent-harness):
prompt di sistema, strumenti, filesystem, esecuzione in sandbox, memoria, gestione del
contesto, pianificazione, subagenti, middleware, approvazione umana e verifica.

## Struttura

- `src/agent_harness`: applicazione finale.
- `steps`: snapshot incrementali. Ogni cartella contiene codice e una guida di replica.
- `notebooks`: micro-esempi LangChain autocontenuti con modelli OpenAI reali.
- `skills`: istruzioni caricate su richiesta dall'agente.
- `workspace`: unica directory condivisa con il container Docker.
- `state`: checkpoint SQLite locali.
- `tests`: test offline, senza consumo di token.

La matrice completa tra articolo e implementazione si trova in
[`docs/HARNESS_COMPONENTS.md`](docs/HARNESS_COMPONENTS.md).

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

Apri `http://127.0.0.1:5173`. Il client usa SSE per mostrare delta del modello, tool,
skills, richieste di approvazione, file prodotti e token rate. `docker_exec` sospende lo
stesso run finché la dashboard non approva o rifiuta il comando.

Funzioni principali:

- creazione, ricerca, rinomina ed eliminazione sessioni;
- upload, download ed eliminazione file per conversazione;
- stop run e approvazione sandbox;
- trace persistente e replay dopo refresh;
- metriche provider e breakdown stimato del contesto;
- sandbox Docker effimera montata solo sul workspace della sessione corrente.

Esecuzione singola:

```bash
uv run harness run "Analizza i file nel workspace e crea report.md"
```

Il modello predefinito è `gpt-5.4-mini`, adatto alle numerose iterazioni di un agente.
`OPENAI_STRONG_MODEL=gpt-5.5` viene usato dal router per compiti lunghi o esplicitamente
complessi. Entrambi sono modificabili senza cambiare codice.

## Sicurezza

Il tool `docker_exec` non esegue comandi sulla macchina host. Ogni chiamata crea un
container effimero con:

- rete disabilitata;
- filesystem root in sola lettura;
- capability Linux rimosse;
- limite di memoria, CPU, processi e tempo;
- mount in scrittura della sola cartella `workspace`;
- approvazione umana prima dell'esecuzione, quando abilitata.

L'immagine contiene Python, Git, pytest e Ruff. Viene costruita con:

```bash
make sandbox-image
```

Docker riduce il rischio ma non costituisce da solo un confine perfetto in ambienti
ostili. Non montare socket Docker, home directory o segreti nel container. Il backend
shell locale non viene usato dal progetto finale.

## Comandi

```bash
make test       # test offline
make lint       # analisi statica
make notebooks       # struttura e compilazione celle, senza chiamate API
make notebooks-live  # esecuzione end-to-end con OPENAI_API_KEY
make sandbox-image # immagine Docker riproducibile
make run        # chat interattiva
```

## Percorso consigliato

1. Seguire le cartelle `steps` in ordine.
2. Ricostruire manualmente ogni avanzamento usando `GUIDA.md`.
3. Aprire i notebook per riprodurre micro-esempi LangChain completi e autocontenuti.
4. Leggere `src/agent_harness` per vedere come i componenti vengono assemblati.

## Tracing

Per inviare le tracce a LangSmith:

```dotenv
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=...
LANGSMITH_PROJECT=langchain-agent-harness
```

Nessuna chiave viene salvata nel codice o stampata nei log.
