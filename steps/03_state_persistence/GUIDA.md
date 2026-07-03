# Step 03 — Stato, checkpoint e thread

## Obiettivo

Spostiamo la cronologia dal processo a SQLite. Una conversazione può così essere ripresa
dopo ogni nodo e, usando lo stesso database, anche dopo un riavvio.

## Concetti

- Il `checkpointer` salva snapshot dello stato LangGraph.
- Il `thread_id` identifica una sequenza di snapshot.
- Due thread nello stesso database rimangono separati.
- Un checkpoint non è memoria globale: appartiene a una conversazione.

## Procedura manuale

1. Installa il backend:

   ```bash
   uv add langgraph-checkpoint-sqlite
   ```

2. Crea `SqliteSaver` con un file dentro `state`.
3. Passalo a `create_agent`.
4. Usa sempre:

   ```python
   config = {"configurable": {"thread_id": "un-id-stabile"}}
   ```

5. Effettua due invocazioni fornendo nel secondo turno soltanto il nuovo messaggio.

## Prova

```bash
mkdir -p state
uv run python -m steps.03_state_persistence.app
```

## Esperimento

Cambia `thread_id` prima della seconda chiamata. Il nuovo thread non conosce il numero.
Ripristina l'ID originale e la cronologia torna disponibile.

## Distinzione essenziale

Il checkpoint conserva stato a breve termine. Una preferenza valida per conversazioni
diverse richiede una memoria lunga, che introdurremo nello step 08.

