# L3 · Ciclo di self-improvement

**Unità:** trasversale → [T.3](../L2_UNITA.md#t3--ciclo-di-self-improvement)

*Dalle trace dei run passati nasce una proposta di modifica; la proposta viene misurata
contro la baseline su un eval set versionato; se il gate passa si attiva una canary con
metriche live; solo dopo si promuove, con rollback sempre disponibile. Il codice non viene
mai toccato.*

Il rischio di un ciclo che si auto-migliora è che impari a **sembrare** migliore. Ogni
vincolo di questa unità esiste per chiudere una via a quella scorciatoia.

---

## Vincolo 1 · Whitelist degli override

```python
# Solo queste chiavi possono essere applicate automaticamente: il resto della config
# resta sotto controllo umano diretto nel codice.
OVERRIDE_WHITELIST = frozenset({"system_prompt_addendum", "harness_max_tool_calls"})
```

**Evidenza:** `improve.py · L16–19`.

Due chiavi. Non «tutto tranne le pericolose» — **solo queste due**. Il filtro è applicato
tre volte in punti diversi, non una sola:

| Funzione | Evidenza |
|---|---|
| `saved_overrides` | `improve.py · L251–260` |
| `replace_override_values` | `improve.py · L275–284` |
| `load_overrides` | `improve.py · L286–292` |

Ridondanza deliberata: sui confini che contano, il filtro sta a ogni attraversamento, non
solo all'ingresso.

**Cosa resta fuori:** la rubric e la soglia di valutazione. Se fossero modificabili,
l'agente potrebbe abbassare l'asticella che lo misura invece di superarla. È la definizione
operativa di reward hacking, e la whitelist la rende impossibile per costruzione.

`overrides_fingerprint` (`improve.py · L294–301`) produce un'impronta stabile della
configurazione: è ciò che lega un run alla versione che lo ha prodotto.

---

## Vincolo 2 · Il gate misura tre cose separate

`evaluate_gate` (`evaluation.py · L216–295`) — *«Separa qualità verificata e affidabilità
del protocollo di completion»*.

### Regressioni: nessuna tolleranza

Un caso che passava nella baseline e non passa nel candidato è una regressione, **anche se
la media migliora** (`evaluation.py · L224–241`). Due liste separate: `check_regressions` e
`completion_regressions`.

Un caso mancante nel candidato conta come regressione, non come dato assente.

### Soglie assolute

| Condizione | Esito |
|---|---|
| check pass rate < 0.8 | bloccato |
| completion rate < 0.8 | bloccato |
| token ratio > 1.2 | bloccato (+20% max) |
| latency ratio > 1.3 | bloccato (+30% max) |

**Evidenza:** `evaluation.py · L268–276`.

Il candidato non può comprare qualità con costo illimitato.

### Serve un miglioramento misurabile

```python
if not quality_improved and not completion_improved and not efficiency_improved:
    reasons.append("Nessun miglioramento misurabile di qualità, completion o efficienza.")
```

**Evidenza:** `evaluation.py · L277–280`.

Non basta «non peggiora». Una modifica che non migliora niente non viene promossa: il
sistema non accumula cambiamenti neutri di cui poi nessuno sa spiegare la ragione.

Le soglie di miglioramento sono esplicite: qualità e completion ≥ +0.01, efficienza ≤ 0.95
(cioè almeno −5% di token o latenza) (`evaluation.py · L259–266`).

`passed = not reasons` (`evaluation.py · L281`): il gate passa solo se **nessuna** ragione di
blocco è stata trovata, e le ragioni sono restituite in chiaro.

---

## Vincolo 3 · Eval set versionato

`eval_set_hash` (`evaluation.py · L144–154`) produce l'impronta dei casi. Confrontare
baseline e candidato su eval set diversi darebbe un risultato senza significato: l'hash
rende il confronto verificabile a posteriori.

`_confined_path` (`evaluation.py · L110–118`) confina i path dei casi. `EVALUATION_SCHEMA_VERSION = 2`
(`evaluation.py · L18`) versiona l'artefatto.

---

## Vincolo 4 · La canary attribuisce i run

`analyze_canary` (`canary.py · L82–180`) — *«Confronta solo run attribuiti alla canary attiva
e ai suoi fingerprint»*.

L'attribuzione è la parte delicata. Un run entra in un braccio solo se il suo evento
`config.selected` soddisfa **tutte** queste condizioni (`canary.py · L98–113`):

1. è successivo all'avvio della canary (`created_at >= started_at`);
2. ha la stessa `source`;
3. il `fingerprint` corrisponde a quello del braccio dichiarato — baseline con
   `baseline_fingerprint`, canary con `candidate_fingerprint`.

Senza il terzo controllo, un run etichettato «canary» ma eseguito con un'altra
configurazione inquinerebbe la misura. Il fingerprint lega l'etichetta alla configurazione
reale.

### Successo ≠ status `completed`

```python
if status == "completed":
    if completed_payloads.get(run_id, {}).get("completed") is False:
        accumulator.incomplete_runs += 1
    else:
        accumulator.successful_runs += 1
```

**Evidenza:** `canary.py · L128–135`.

Un run può avere status `completed` — è terminato — ma payload `completed=false`, cioè
budget di continuazione esaurito senza verifica. Contarlo come successo gonfierebbe le
metriche del braccio. Stessa distinzione degli
[stati durevoli](lavoro-durevole.md#gli-stati).

### Minimo di run per braccio

`MINIMUM_RUNS_PER_ARM = 5` (`canary.py · L13`): sotto quella soglia non si conclude nulla.
Una canary con due run per braccio non è un esperimento.

---

## Vincolo 5 · Promozione validata e reversibile

`_validated_candidate` (`promotion.py · L92–112`) ricontrolla prima di promuovere; la
promozione richiede una valutazione salvata con gate passato
(`promotion.py · L113–145`).

`record_config_version` (`promotion.py · L24–44`) salva ogni versione,
`list_config_versions` le elenca, `restore_config_version` (`promotion.py · L59–81`) torna
indietro a qualunque versione precedente.

Il rollback non è una procedura d'emergenza documentata a parte: è una funzione con la
stessa dignità della promozione.

---

## Vincolo 6 · Propose-only

Il ciclo **non modifica il codice**. Scrive proposte in `state/improvements/`
(`improve.py · L229–250`), esegue baseline e candidato sull'eval set, e abilita canary o
promotion solo se il gate passa.

`build_report` (`improve.py · L116–182`) aggrega gli ultimi N **run terminali**, non gli
eventi: delta di streaming e audit storici non falsano le statistiche.

---

## Riepilogo evidenza

| Sito | Righe | Ruolo |
|---|---|---|
| `src/agent_harness/improve.py` | L16–19 | whitelist degli override |
| `src/agent_harness/improve.py` | L116–182 | report dai run terminali |
| `src/agent_harness/improve.py` | L229–250 | scrittura della proposta |
| `src/agent_harness/improve.py` | L251–301 | filtro ripetuto e fingerprint |
| `src/agent_harness/evaluation.py` | L18, L110–118 | versione schema e path confinati |
| `src/agent_harness/evaluation.py` | L144–154 | hash dell'eval set |
| `src/agent_harness/evaluation.py` | L156–215 | esecuzione dei check e sintesi |
| `src/agent_harness/evaluation.py` | L216–295 | il gate |
| `src/agent_harness/evaluation.py` | L297–490 | run appaiato baseline/candidato |
| `src/agent_harness/canary.py` | L8–13 | eventi rilevanti e minimo per braccio |
| `src/agent_harness/canary.py` | L16–80 | metriche e accumulatori |
| `src/agent_harness/canary.py` | L82–180 | attribuzione e analisi |
| `src/agent_harness/promotion.py` | L24–81 | versioni e rollback |
| `src/agent_harness/promotion.py` | L92–145 | promozione validata |

**Test:** `tests/test_improve.py`, `tests/test_evaluation.py`, `tests/test_canary.py`,
`tests/test_promotion.py`.

Approfondimento con le formule del gate: [`../../SELF_IMPROVEMENT.md`](../../SELF_IMPROVEMENT.md).

---

## Note per chi modifica

- **Non aggiungere chiavi alla whitelist senza chiedersi se l'agente potrebbe usarle per
  sembrare migliore.** Rubric e soglie non ci vanno mai.
- **Non ammorbidire le regressioni.** «La media è migliorata» è esattamente l'argomento che
  la lista dei casi regrediti esiste per respingere.
- **Non rimuovere il requisito di miglioramento misurabile.** Senza, il sistema accumula
  modifiche neutre.
- **Non attribuire i run per etichetta senza fingerprint.** L'etichetta dice cosa doveva
  essere; il fingerprint dice cosa è stato.
- `MINIMUM_RUNS_PER_ARM` è una soglia statistica, non un parametro di comodità: abbassarla
  produce conclusioni che sembrano dati.
