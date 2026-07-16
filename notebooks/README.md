# Notebook didattici autonomi

Dodici notebook pensati per **capire un concetto alla volta**. Ogni notebook è:

- **autonomo**: definisce da sé configurazione, tool e agente; non importa nulla dal progetto
  (`src`, `steps`), quindi può essere eseguito da solo;
- **granulare**: celle piccole, un'idea per cella, con spiegazioni prima di ogni passo;
- **commentato**: il codice ha commenti che spiegano riga per riga cosa succede.

Ogni notebook applica inoltre un contratto didattico uniforme:

- obiettivi, prerequisiti e durata indicativa all'inizio;
- una spiegazione dedicata immediatamente prima di **ogni** blocco codice;
- una sezione **Output atteso** immediatamente dopo ogni blocco, con invarianti e parti
  non deterministiche chiaramente distinte;
- almeno due esempi aggiuntivi, incluso un caso limite, errore o controllo negativo;
- riepilogo e troubleshooting finale.

I notebook 01-06 usano LangChain e modelli reali: richiedono ambiente Python del progetto,
`OPENAI_API_KEY` e `OPENAI_MODEL` dal file `.env`; il 04 usa anche `OPENAI_STRONG_MODEL`.
I notebook 07-12 usano **solo Python standard library**: nessuna chiave, rete, API o import dal
progetto. “Autonomo” significa anche che nessun notebook importa un altro notebook o uno step.

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

### Mini-serie avanzata · governance operativa, offline

7. `07_provider_capability_e_costi.ipynb`
   - contratti provider-neutral, capability preflight, costi e tassonomia errori.

8. `08_budget_contesto_e_run.ipynb`
   - misura contesto, offload recuperabile, prenotazione e riconciliazione budget.

9. `09_esecuzione_durevole_e_hitl.ipynb`
   - state machine SQLite, idempotenza, lease concettuale, interrupt attraverso restart.

10. `10_governance_subagenti.ipynb`
    - roster, least privilege, fallback compatibile, cicli, review indipendente e prove.

11. `11_manifest_e_delivery_gate.ipynb`
    - manifest canonico, tamper detection, snapshot read-only e gate delivery.

12. `12_eval_canary_e_rollback.ipynb`
    - eval paired, regression gate, canary stabile, promotion e rollback append-only.

## Configurazione

```dotenv
OPENAI_API_KEY=...
OPENAI_MODEL=gpt-5.4-mini
OPENAI_STRONG_MODEL=gpt-5.5
```

## Validazione

Controllo strutturale più esecuzione reale dei notebook offline 07-12:

```bash
make notebooks
```

Solo controllo strutturale di tutti i notebook:

```bash
uv run python scripts/validate_notebooks.py
```

Il validatore rifiuta notebook privi di spiegazione, output atteso o esempi aggiuntivi. Per
riapplicare in modo idempotente il contratto didattico dopo modifiche manuali:

```bash
uv run python scripts/enrich_notebooks.py
```

Esecuzione completa con modelli reali (effettua chiamate OpenAI, può generare costi):

```bash
make notebooks-live
```

Le copie eseguite finiscono in una cartella temporanea; i notebook sorgente restano senza
output e possono essere rieseguiti dall'inizio.
