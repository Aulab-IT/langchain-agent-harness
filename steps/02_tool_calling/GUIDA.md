# Step 02 — Tool calling e ciclo ReAct

## Obiettivo

Permettiamo al modello di scegliere uno strumento, riceverne il risultato e continuare
fino alla risposta.

## Il ciclo

`create_agent` costruisce sopra LangGraph questo ciclo:

1. il modello legge messaggi e descrizioni dei tool;
2. può rispondere oppure emettere una tool call strutturata;
3. l'harness valida gli argomenti ed esegue la funzione;
4. il risultato diventa un `ToolMessage`;
5. il modello viene richiamato con la nuova osservazione.

Questo è il nucleo del pattern ReAct. Il modello decide l'azione; l'harness la esegue.

## Procedura manuale

1. Definisci una funzione Python con tipi e docstring.
2. Applicale `@tool`. La firma diventa lo schema JSON visto dal modello.
3. Passa il tool a `create_agent`.
4. Invoca il graph con una lista `messages`.
5. Ispeziona tutti i messaggi:

   ```python
   for message in result["messages"]:
       print(type(message).__name__, message.content)
   ```

## Prova

```bash
uv run python -m steps.02_tool_calling.app
```

Vedrai almeno un messaggio umano, una richiesta del modello, un risultato del tool e la
risposta finale.

## Regola importante

La docstring non è decorazione: orienta la scelta del modello. Argomenti tipizzati
permettono all'harness di rifiutare input incompatibili.

## Esercizio

Aggiungi un tool `percentage(value, rate)` e formula una domanda che richieda entrambi i
tool nello stesso turno.

