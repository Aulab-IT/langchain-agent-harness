# Step 10 — Subagenti e model routing

## Obiettivo

Manteniamo pulito il contesto del coordinatore e assegniamo risorse diverse in base al
tipo di lavoro.

## Subagente

Un subagente riceve una consegna delimitata, un prompt e un insieme di tool. Il suo
ragionamento intermedio rimane nel contesto isolato; al coordinatore torna il risultato
finale. Questo è utile per:

- ricerche con molte chiamate;
- revisioni indipendenti;
- competenze e permessi diversi.

Non delegare un'azione banale: il passaggio di contesto ha un costo.

## Model routing

`@wrap_model_call` intercetta ogni chiamata. Il middleware può sostituire il modello
senza cambiare il graph. L'esempio usa:

- `gpt-5.4-mini` per turni ordinari;
- `gpt-5.5` quando la cronologia supera una soglia.

Nel progetto finale vengono considerate anche parole che segnalano complessità.

## Procedura manuale

1. Crea due istanze `ChatOpenAI`.
2. Scrivi un middleware `route`.
3. Usa `request.override(model=selected)`.
4. Definisci il subagente con nome, descrizione, prompt, tool e modello.
5. Passa middleware e subagenti a `create_deep_agent`.

## Prova

```bash
uv run python -m steps.10_subagents_and_routing.app
```

Per osservare la delegazione assegna un artefatto multi-file e chiedi esplicitamente una
revisione indipendente.

## Esercizio

Aggiungi un subagente `researcher` che possiede `web_search`, mentre il revisore non può
accedere alla rete.

