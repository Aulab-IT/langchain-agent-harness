# L3 · Budget di run

**Unità:** stadio 5 → [5.3](../L2_UNITA.md#53--budget-di-run)

*Un run ha un costo massimo in token, dollari, chiamate e secondi. Il tracker prenota prima
di chiamare e riconcilia dopo, così chiamate parallele non superano insieme il residuo. Dopo
un superamento nessuna nuova chiamata al modello è ammessa.*

Da non confondere con il [budget di contesto](budget-di-contesto.md): quello governa
**quanto entra** in una singola richiesta, questo governa **quanto costa** il run intero.

---

## Il problema: la concorrenza

Il docstring del modulo dichiara il meccanismo e il motivo:

> «Il tracker è condiviso da root, router, grader e subagent. Prenota costo/token prima di
> una chiamata per evitare che call parallele superino insieme il residuo, poi riconcilia la
> prenotazione con l'usage reale del provider. Dopo un superamento nessuna nuova chiamata
> modello è ammessa.»

**Evidenza:** `run_budget.py · L1–6`.

Il controllo ingenuo — «guarda il consumato, se c'è spazio chiama» — fallisce con quattro
chiamate concorrenti: tutte leggono lo stesso residuo e partono tutte. La prenotazione
esiste per chiudere quella finestra.

Ciclo in tre tempi:

```
reserve   stima conservativa, decrementa subito il residuo
   ↓
chiamata al provider
   ↓
settle    sostituisce la stima con l'usage reale
```

Tutto sotto una `threading.RLock` (`run_budget.py · L208`): il tracker è condiviso tra
componenti che girano in thread diversi.

---

## Le dimensioni

`RunBudgetLimits` (`run_budget.py · L86–111`) — sette limiti più due parametri:

| Limite | Governa |
|---|---|
| `max_tokens` | token totali del run |
| `max_cost_usd` | costo in dollari |
| `max_seconds` | durata |
| `max_model_calls` | numero di chiamate al modello |
| `max_subagent_calls` | numero di deleghe |
| `max_subagent_model_calls` | chiamate fatte **dentro** i subagenti |
| `max_subagent_tokens` | token consumati dai subagenti |
| `reserved_output_tokens` | spazio riservato all'output |
| `warning_ratio` | soglia di allerta |

Tre dimensioni su sette riguardano i subagenti. Non è ridondanza: una delega può moltiplicare
il costo senza aumentare il numero di chiamate del padre, e senza limiti dedicati sarebbe la
via più semplice per aggirare il budget.

---

## Il costo si calcola in `Decimal`

`BudgetRate.cost` (`run_budget.py · L79–84`) usa `Decimal` per tutto il percorso, e
`from_values` converte passando da `str` — `Decimal(str(0.1))`, non `Decimal(0.1)`
(`run_budget.py · L64–77`).

Il float qui accumulerebbe errore su migliaia di chiamate, e un budget che sfora per
arrotondamento è un budget che non si può difendere.

I limiti sono espressi «per milione di token» e divisi da `_MILLION` alla fine, non a ogni
addendo (`run_budget.py · L80–84`).

---

## Superamento

```python
raise BudgetExceededError(self._exceeded_dimension, self._exceeded_reason)
```

**Evidenza:** `run_budget.py · L303`.

L'eccezione porta con sé **quale** dimensione è esaurita (`run_budget.py · L29–35`), non solo
il fatto che lo sia. La CLI lo mostra come messaggio distinto da un errore generico
(`cli.py · L82–83`), e lo stato terminale del run diventa `budget_exceeded`, non `failed` —
vedi [lavoro durevole](lavoro-durevole.md#gli-stati).

Lo stato di superamento è **assorbente**: una volta esaurito, ogni chiamata successiva
solleva senza nemmeno provare.

---

## Snapshot osservabile

`RunBudgetSnapshot` (`run_budget.py · L123–144`) espone tutto ciò che serve a capire dove si
sta andando **prima** di sbattere: consumo cumulativo, costo, chiamate, elapsed, e i quattro
rapporti (`token_ratio`, `cost_ratio`, `model_call_ratio`, `subagent_call_ratio`), più
`exceeded_dimension` e `exceeded_reason`.

`by_call_kind` separa il consumo per tipo di chiamata: si vede quanto è costato il grader
rispetto al lavoro vero.

---

## Casi limite

### Tentativi falliti in streaming

Un tentativo che fallisce a metà stream ha comunque consumato input dal provider. Il tracker
lo *«conta conservativamente»* (`run_budget.py · L435`): la stima prudente è preferibile al
non contarlo, perché un errore ripetuto sarebbe altrimenti gratis.

### Stop esterno

`run_budget.py · L601` registra uno stop esterno — per esempio il timeout dell'intero
coroutine del run — nella stessa struttura, così l'esito è coerente con le altre dimensioni
invece di essere un percorso a parte.

### Ultima chiamata riservata alla consegna

Il budget dei subagenti applica *«pressione precoce e ultima call riservata alla consegna»*
(`run_budget.py · L606–614`). Un subagente che esaurisce il budget senza poter rispondere
sprecherebbe tutto ciò che ha già speso: l'ultima chiamata è tenuta da parte perché possa
almeno consegnare il risultato parziale.

### Progresso affidabile

`SubagentProgressState` (`run_budget.py · L37–52`) condivide col middleware del modello i
segnali *prodotti dai tool* — cioè fatti osservati, non affermazioni del modello su sé
stesso. La distinzione conta: un modello che dice «sto facendo progressi» non è evidenza di
progresso.

---

## Riepilogo evidenza

| Sito | Righe | Ruolo |
|---|---|---|
| `src/agent_harness/run_budget.py` | L1–6 | prenotazione, riconciliazione, stop assorbente |
| `src/agent_harness/run_budget.py` | L29–35 | eccezione con dimensione |
| `src/agent_harness/run_budget.py` | L37–52 | progresso da segnali dei tool |
| `src/agent_harness/run_budget.py` | L54–84 | tariffe in `Decimal` |
| `src/agent_harness/run_budget.py` | L86–111 | le sette dimensioni |
| `src/agent_harness/run_budget.py` | L113–121 | prenotazione |
| `src/agent_harness/run_budget.py` | L123–144 | snapshot osservabile |
| `src/agent_harness/run_budget.py` | L157–199 | stima della richiesta e usage della risposta |
| `src/agent_harness/run_budget.py` | L201–303 | ledger concorrente e hard stop |
| `src/agent_harness/run_budget.py` | L606–620 | budget dei subagenti |
| `src/agent_harness/pricing.py` | L139–221 | catalogo prezzi e calcolo costi |
| `src/agent_harness/usage.py` | — | stima token |

**Test:** `tests/test_run_budget.py`, `tests/test_pricing.py`.

---

## Note per chi modifica

- **Non sostituire `Decimal` con `float`.** L'errore di arrotondamento su migliaia di
  chiamate rende il limite indifendibile.
- **Non rimuovere la prenotazione** in favore di un controllo post-hoc: riapre la finestra
  di concorrenza che l'unità esiste per chiudere.
- **Aggiungere una dimensione** → serve il limite, il rapporto nello snapshot e il caso in
  `BudgetExceededError`. Senza il rapporto non è osservabile prima del superamento, che è
  metà del valore.
- I limiti sui subagenti non sono opzionali: sono la strada più corta per aggirare il budget
  del padre.
