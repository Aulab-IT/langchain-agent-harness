# Step 06 — Ricerca web e Model Context Protocol

## Obiettivo

Colleghiamo l'agente a conoscenza non presente nei pesi del modello e a un server di tool
indipendente dal processo principale.

## Due meccanismi diversi

La ricerca web recupera informazioni recenti. MCP standardizza come un processo esterno
descrive ed espone strumenti. Un server MCP può rappresentare un database, un servizio
aziendale o, come nell'esempio, un glossario locale.

## Procedura per la ricerca

1. Crea un tool con input `query` e `max_results`.
2. Limita lunghezza della query e numero di risultati.
3. Restituisci titolo, URL ed estratto.
4. Anteponi un confine esplicito: i risultati sono dati non attendibili.

Questa separazione attenua la prompt injection. Non elimina la necessità di verificare
fonti e autorizzazioni.

## Lettura di una pagina

Gli snippet di ricerca non bastano per verificare una fonte. `browser_read` recupera il
testo della pagina senza eseguire JavaScript. Prima di ogni connessione e redirect:

- accetta soltanto HTTP e HTTPS;
- rifiuta credenziali nell'URL;
- blocca indirizzi privati, loopback, link-local e riservati;
- limita tipo e dimensione della risposta.

Il contenuto resta non attendibile e non può diventare una nuova istruzione.

## Procedura per MCP

1. Apri `src/agent_harness/mcp_server.py`.
2. Crea `FastMCP` e registra funzioni con `@mcp.tool()`.
3. Avvia il server con trasporto `stdio`.
4. Nel client configura comando, argomenti e trasporto.
5. Chiama `await client.get_tools()`.
6. Passa i tool restituiti a `create_agent`.

## Prova

```bash
uv run python -m steps.06_search_and_mcp.app
```

## Cosa osservare

Il modello vede uno schema uniforme anche se `web_search` e `browser_read` sono funzioni
nel processo e `harness_glossary` arriva da un sottoprocesso MCP.

## Esercizio

Aggiungi al server un tool `word_frequency(text, word)`. Riavvia lo step e chiedi
all'agente di usarlo.
