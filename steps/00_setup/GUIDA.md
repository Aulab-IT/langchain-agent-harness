# Step 00 — Preparare il progetto

## Obiettivo

In questo primo avanzamento prepariamo un ambiente riproducibile e separiamo il codice
dai segreti. Non chiamiamo ancora il modello.

## Concetto

La configurazione appartiene all'harness. Il modello non deve conoscere la chiave API e
il codice non deve contenerla. `pydantic-settings` legge le variabili d'ambiente e
interrompe subito l'avvio quando manca un valore obbligatorio.

## Procedura manuale

1. Crea una directory vuota e inizializza il progetto:

   ```bash
   uv init --python 3.11
   uv add langchain langchain-openai pydantic-settings
   ```

2. Crea `.env`:

   ```dotenv
   OPENAI_API_KEY=
   OPENAI_MODEL=gpt-5.4-mini
   ```

3. Aggiungi `.env` a `.gitignore`. Non usare una chiave fittizia nel repository: anche
   un esempio che assomiglia a una chiave può finire per essere copiato o pubblicato.

4. Copia la classe `Settings` da `app.py`.

5. Esegui:

   ```bash
   uv run python steps/00_setup/app.py
   ```

## Cosa osservare

Senza `OPENAI_API_KEY` il programma fallisce prima di effettuare richieste. Con la
variabile presente mostra soltanto il nome del modello; la chiave è esclusa dall'output.

## Esercizio

Aggiungi un campo intero `max_tool_calls` con valore predefinito 20 e vincolo tra 1 e 100.
