# Notebook didattici autonomi

Sei notebook pensati per **capire un concetto alla volta**. Ogni notebook è:

- **autonomo**: definisce da sé configurazione, tool e agente; non importa nulla dal progetto
  (`src`, `steps`), quindi può essere eseguito da solo;
- **granulare**: celle piccole, un'idea per cella, con spiegazioni prima di ogni passo;
- **commentato**: il codice ha commenti che spiegano riga per riga cosa succede.

Tutti usano `OPENAI_API_KEY` e `OPENAI_MODEL` dal file `.env`; il notebook 04 usa anche
`OPENAI_STRONG_MODEL` per mostrare il routing del modello.

## Percorso

1. `01_da_llm_ad_agente.ipynb`
   - chiamata diretta al modello;
   - una chain LCEL (`prompt | model | parser`);
   - un agente con un tool e il suo loop ReAct, con ispezione dei messaggi.

2. `02_tools_filesystem_e_sandbox.ipynb`
   - un tool tipizzato;
   - tool su file confinati in un workspace (prevenzione del path traversal);
   - esecuzione di codice in un sottoprocesso isolato con timeout.

3. `03_memoria_e_contesto.ipynb`
   - il problema: le chiamate sono senza memoria;
   - memoria di breve termine con checkpointer + `thread_id`;
   - memoria di lungo termine con uno store e due tool (ricorda / richiama).

4. `04_planning_e_subagenti.ipynb`
   - un tool per definire il piano;
   - un subagente usato come tool (isolamento del contesto);
   - routing del modello con un middleware `wrap_model_call`.

5. `05_harness_completo.ipynb`
   - un tool con effetto collaterale (email simulata);
   - audit middleware attorno ai tool;
   - limite deterministico di tool call;
   - verifica del risultato con codice, non col modello.

6. `06_loop_engineering.ipynb`
   - Loop 2: verifica con una rubrica e feedback;
   - Loop 3: trigger a eventi (match di un'espressione cron);
   - Loop 4: hill climbing, da un report a una proposta (propose-only).

## Configurazione

```dotenv
OPENAI_API_KEY=...
OPENAI_MODEL=gpt-5.4-mini
OPENAI_STRONG_MODEL=gpt-5.5
```

## Validazione

Controllo strutturale (compila le celle, senza chiamate API):

```bash
make notebooks
```

Esecuzione completa con modelli reali (effettua chiamate OpenAI, può generare costi):

```bash
make notebooks-live
```

Le copie eseguite finiscono in una cartella temporanea; i notebook sorgente restano senza
output e possono essere rieseguiti dall'inizio.
