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

- zero regressioni nei check deterministici;
- zero regressioni nel protocollo di completion;
- check pass rate candidato almeno `0.8`;
- completion rate candidato almeno `0.8`;
- token non oltre `+20%`;
- latenza non oltre `+30%`;
- miglioramento misurabile di qualità, completion, token o latenza.

Qualità output e completion sono metriche separate. Un artefatto può superare tutti i check
ma non chiudere correttamente il loop entro budget: UI mostra entrambi gli esiti e il feedback
del grader per ogni caso. Le evaluation usano una sola continuation esterna per caso
(`HARNESS_EVAL_MAX_CONTINUATIONS=1`) così un errore di protocollo non moltiplica inutilmente
token e latenza.

L'evaluation è esplicita perché esegue due run per caso e consuma API. Risultati completi vivono
in `state/evaluations/`; il sidecar della proposta lega evaluation e override tramite hash.
Se baseline o proposta cambiano, la promotion viene rifiutata e serve una nuova evaluation.
Artefatti con schema precedente vengono ignorati e devono essere rigenerati.

## Canary, versioni e rollback

Una proposta passata può:

- diventare canary per una quota `5–50%` delle sessioni;
- essere promossa al `100%`.

Routing canary usa hash stabile del `session_id`: stessa sessione conserva stessa configurazione.
Promotion piena salva versione precedente e nuova sotto `state/config_versions/`. Rollback
registra a sua volta snapshot pre/post e disattiva eventuale canary.

Ogni run emette `config.selected` con arm (`baseline`/`canary`), fingerprint e proposta sorgente.
Control Center aggiorna ogni 15 secondi confronto live su:

- success e failure rate;
- score grader;
- token medi;
- latenza media.

Gate live parte dopo almeno 5 run per arm. Canary passa se resta entro 5 punti di success/failure
rate, 0.03 di score grader, `+20%` token e `+30%` latenza rispetto alla baseline. Se una canary è
attiva, promotion al 100% viene bloccata finché gate live non passa. Run storici senza attribution
o appartenenti a esperimenti precedenti vengono ignorati.

Control Center espone evaluation, confronto baseline/candidato, canary live, promotion e
ripristino. API resta vincolata a `127.0.0.1`; endpoint evaluation accetta una sola esecuzione
concorrente.
