# Step 17 — Governance dei subagenti

## Obiettivo

Delegare per isolamento o specializzazione, non per nome o intuizione. Il router propone; codice
deterministico verifica che agenti, tool, permessi, dipendenze e review siano realmente validi.

## Contratto

Ogni profilo dichiara capacità, input, output, vincoli, tool, tier e modalità read-only. Ogni task
dichiara requisiti, criterio di successo, dipendenze e necessità di scrittura. `validate_plan`
rimuove nomi inventati, seleziona un’alternativa compatibile, impedisce a un agente read-only di
scrivere, chiude dipendenze mancanti, blocca cicli e richiede reviewer indipendente.

Lo step propone apposta `researcher` per un task Python mutativo. Il validatore sceglie `builder`,
unica alternativa con capability `python`, tool `docker_exec` e permesso di scrittura.

## Esecuzione

```bash
uv run python steps/17_subagent_governance/app.py
```

Rimuovi `builder` dalle alternative: il task viene scartato. Aggiungi due task indipendenti senza
dipendenze: possono partire in parallelo, ma condividono comunque il budget del run.

## Protocollo di uscita

Nel sistema completo un subagente deve produrre stato, prove e artefatti. Un testo plausibile senza
evidenza non basta per dichiarare il task completato.
