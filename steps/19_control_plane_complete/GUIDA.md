# Step 19 — Control plane e sistema completo

## Obiettivo

Arrivare allo stato più vicino all’agente attuale: stesso backend reale, non una reimplementazione
didattica. Lo script importa l’app FastAPI finale, inventaria le route e, con `--serve`, avvia API.

## Cosa assembla

Il control plane collega sessioni isolate, chat streaming SSE, upload e preview sicure, trace, usage,
budget, sandbox, memoria, skill, catalogo tool/MCP, roster subagenti, interrupt durevoli, trigger cron
e webhook, eval, canary, rollback, manifest evidenze e delivery gate. SQLite conserva control state e
checkpoint; workspace separati conservano artefatti.

Il client React non contiene logica di esecuzione: rende stato del backend, invia decisioni HITL e
mostra prove. Questa separazione consente CLI e UI sullo stesso harness.

## Inventario offline

```bash
uv run python steps/19_control_plane_complete/app.py
```

## Avvio completo

```bash
# terminale 1
uv run python steps/19_control_plane_complete/app.py --serve

# terminale 2
cd client
npm install
npm run dev
```

Apri `http://127.0.0.1:5173`. Per un run reale servono provider configurato e, per esecuzione di
codice, immagine Docker descritta nello step 05. L’API resta su loopback: non include autenticazione
o tenancy da servizio pubblico.

## Verifica finale

Usa `make test`, `make lint`, `make notebooks` e `cd client && npm run build`. Poi esegui un task che
crea artefatto, verifica il dossier Evidence e controlla che delivery resti chiusa senza CI/preview.
