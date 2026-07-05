# Self-improvement loop

Il progetto usa un ciclo controllato. Nessuna proposta modifica direttamente codice o config
attiva.

```text
run correlati
  → weakness report
  → proposta whitelisted
  → baseline vs candidato
  → regression gate
  → canary 5–50%
  → promotion versionata oppure rollback
```

## Spazio di ricerca

Sono modificabili solo:

- `system_prompt_addendum`;
- `harness_max_tool_calls`.

Rubric e `harness_rubric_threshold` restano congelate. Permetterne la modifica al sistema che
ottimizza il pass rate consentirebbe reward hacking.

## Eval set

[`evals/cases.json`](../evals/cases.json) contiene task piccoli e verificabili. Ogni caso ha:

- `id` stabile;
- `goal`;
- fixture testuali opzionali in `files`;
- check deterministici `answer_contains`, `answer_regex`, `file_exists`, `file_contains`.

Baseline e candidato usano workspace e thread separati. L'ordine viene alternato tra casi per
ridurre order bias. Il gate richiede:

- zero regressioni su casi prima passati;
- pass rate candidato almeno `0.8`;
- token non oltre `+20%`;
- latenza non oltre `+30%`;
- miglioramento misurabile di qualità, token o latenza.

L'evaluation è esplicita perché esegue due run per caso e consuma API. Risultati completi vivono
in `state/evaluations/`; il sidecar della proposta lega evaluation e override tramite hash.
Se baseline o proposta cambiano, la promotion viene rifiutata e serve una nuova evaluation.

## Canary, versioni e rollback

Una proposta passata può:

- diventare canary per una quota `5–50%` delle sessioni;
- essere promossa al `100%`.

Routing canary usa hash stabile del `session_id`: stessa sessione conserva stessa configurazione.
Promotion piena salva versione precedente e nuova sotto `state/config_versions/`. Rollback
registra a sua volta snapshot pre/post e disattiva eventuale canary.

Control Center espone evaluation, confronto baseline/candidato, canary, promotion e ripristino.
API resta vincolata a `127.0.0.1`; endpoint evaluation accetta una sola esecuzione concorrente.
