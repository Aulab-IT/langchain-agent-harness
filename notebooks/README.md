# Notebook didattici autocontenuti

Ogni notebook definisce al proprio interno configurazione, tool, middleware e graph usati
nell'esempio. Non importa codice da `src`, `steps` o altri file del progetto.

I notebook usano:

- `OPENAI_API_KEY` dal file `.env`;
- `OPENAI_MODEL` come modello principale;
- `OPENAI_STRONG_MODEL` quando l'esempio richiede model routing.

## Percorso

1. `01_da_llm_ad_agente.ipynb`
   - invocazione diretta di `ChatOpenAI`;
   - chain LCEL;
   - agente ReAct con tool calling reale.

2. `02_tools_filesystem_e_sandbox.ipynb`
   - tool filesystem confinati;
   - path traversal prevention;
   - coding agent con esecuzione in container Docker.

3. `03_memoria_e_contesto.ipynb`
   - checkpoint SQLite;
   - short-term memory per thread;
   - `SummarizationMiddleware`;
   - long-term memory con LangGraph Store e `ToolRuntime`.

4. `04_planning_e_subagenti.ipynb`
   - `TodoListMiddleware`;
   - supervisor con analista e revisore;
   - context isolation;
   - model routing tramite `wrap_model_call`.

5. `05_harness_completo.ipynb`
   - tool tipizzati e side effect;
   - human-in-the-loop;
   - checkpoint e ripresa;
   - tool-call limit;
   - audit middleware;
   - gate di verifica deterministico.

## Configurazione

Inserire una chiave valida:

```dotenv
OPENAI_API_KEY=...
OPENAI_MODEL=gpt-5.4-mini
OPENAI_STRONG_MODEL=gpt-5.5
```

Il notebook Docker richiede Docker Desktop attivo e l'immagine `python:3.12-slim`,
scaricabile con:

```bash
docker pull python:3.12-slim
```

## Validazione

Controllo strutturale e compilazione delle celle, senza chiamate API:

```bash
make notebooks
```

Esecuzione completa con modelli reali:

```bash
make notebooks-live
```

L'esecuzione live effettua più chiamate OpenAI e può generare costi. Le copie eseguite
sono salvate soltanto in una directory temporanea; i notebook sorgente restano senza
output e possono essere rieseguiti dall'inizio.

