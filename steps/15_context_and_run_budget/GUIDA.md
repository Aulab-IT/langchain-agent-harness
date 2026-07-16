# Step 15 — Budget di contesto e budget del run

## Obiettivo

Controllare due risorse diverse: ciò che entra nella finestra del modello e ciò che l’intero run
può consumare. Confonderle produce agenti che compattano troppo tardi o spendono oltre il limite.

## Due livelli

`ContextBudgetManager` misura system prompt, messaggi, tool output e dati ricostruibili. Prima di
chiedere un riassunto al modello preferisce operazioni economiche: scaricare output lunghi su file,
tenere checksum ed estratto, rimuovere osservazioni duplicate. Una riserva protegge lo spazio
necessario alla risposta finale.

`RunBudgetTracker` è invece un ledger concorrente condiviso da root, grader e subagenti. Prima di
ogni chiamata prenota token e costo; dopo la risposta riconcilia la prenotazione con usage reale.
Questo evita che chiamate parallele consumino entrambe lo stesso residuo. Limita anche durata,
numero chiamate modello e quota dei subagenti.

## Esecuzione

```bash
uv run python steps/15_context_and_run_budget/app.py
```

Riduci `max_tokens` o `max_cost_usd`: il tracker rifiuterà la chiamata prima del provider. Aumenta
l’output del tool e osserva l’azione `offload_tool_output`. Il file completo resta recuperabile;
il modello vede solo riferimento, checksum ed estratto.

## Importanza

Budget preventivi trasformano costo e latenza da sorpresa finale a vincolo operativo verificato.
