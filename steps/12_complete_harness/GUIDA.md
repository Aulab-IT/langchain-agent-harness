# Step 12 — Assemblare l'harness completo

## Obiettivo

Colleghiamo i meccanismi precedenti in una sola applicazione senza nasconderne i confini.

## Ordine di assemblaggio

Apri `src/agent_harness/factory.py` e ricostruisci il sistema in questo ordine:

1. valida configurazione e directory;
2. crea modello economico e modello forte;
3. registra tool locali, ricerca e MCP;
4. configura filesystem e permessi;
5. definisci subagenti;
6. aggiungi router e limite tool;
7. collega memoria e skills;
8. abilita interrupt per la sandbox;
9. collega checkpoint SQLite;
10. escludi il tool `execute` incorporato, perché il backend filesystem non è una sandbox;
11. crea il graph Deep Agents e usa soltanto `docker_exec` per i comandi.

`build_harness` è un async context manager perché connessione SQLite e client esterni
devono avere un ciclo di vita esplicito.

## Esecuzione

```bash
cp .env.example .env
# Configura OPENAI_API_KEY
uv sync --extra dev
uv run harness doctor
uv run harness chat
```

## Verifica architetturale

Controlla `docs/HARNESS_COMPONENTS.md`. Per ogni riga individua:

- comportamento desiderato;
- componente di codice;
- stato persistito;
- limite o rischio;
- prova automatica disponibile.

## Tracing

Abilita LangSmith soltanto dopo aver configurato una chiave dedicata. Le tracce permettono
di osservare routing, compaction, tool call, subagenti e interrupt. Prima di inviare dati
a un servizio esterno verifica quali contenuti possono comparire nei prompt.

## Esercizio finale

Assegna questo obiettivo:

> Crea nel workspace un piccolo programma Python, aggiungi test, eseguili nel sandbox,
> chiedi al revisore un controllo e conserva un report di verifica.

Valuta il risultato usando artefatti e log, non soltanto la risposta finale del modello.
