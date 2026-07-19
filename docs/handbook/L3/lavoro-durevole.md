# L3 · Lavoro durevole

**Unità:** stadio 6 · persistenza e proiezione → [6.1](../L2_UNITA.md#61--lavoro-durevole)

*Lo stato del lavoro vive su SQLite, non nel processo. Un riavvio del backend non marca i
run come falliti né perde gli interrupt pendenti: `asyncio.Task` torna a essere un dettaglio
esecutivo, non la fonte di verità.*

---

## Le due garanzie

Il docstring del modulo le dichiara esplicitamente (`durable.py · L11–17`):

> - **transizioni validate con optimistic locking**: ogni scrittura dichiara la versione che
>   si aspetta; se un altro worker ha già cambiato l'item, la transizione viene rifiutata;
> - **idempotency key su ogni side effect**: creare un run, far scattare un trigger o
>   rispondere a un'approvazione due volte non produce due esecuzioni.

Tutto il resto del modulo è l'applicazione di queste due.

Scelta di storage dichiarata insieme al suo limite: prima iterazione su SQLite, con
l'indicazione che «quando servirà multi-host, un adattatore Postgres/Redis sostituisce lo
storage senza toccare l'application service» (`durable.py · L6–9`).

---

## Gli stati

`RunState` (`durable.py · L32–54`) — tredici stati, di cui nove terminali.

| Categoria | Stati |
|---|---|
| In corso | `QUEUED`, `RUNNING`, `RETRY_SCHEDULED` |
| In attesa di un umano | `WAITING_APPROVAL`, `WAITING_USER_ACTION` |
| Terminali di successo | `COMPLETED` |
| Terminali di esito | `INCOMPLETE`, `FAILED_VERIFICATION`, `BLOCKED_NEEDS_HUMAN`, `NO_WORK` |
| Terminali di limite | `BUDGET_EXCEEDED`, `SECURITY_STOP` |
| Terminali di errore | `FAILED`, `CANCELLED` |

La granularità è deliberata. `COMPLETED` e `INCOMPLETE` sono separati per eliminare un
mismatch reale: *«oggi un run tecnicamente terminato può avere status `completed` ma payload
`completed=false`»* (`durable.py · L34–37`).

Distinguere `BLOCKED_NEEDS_HUMAN` da `FAILED`, o `BUDGET_EXCEEDED` da `FAILED`, è ciò che
permette al [ciclo di self-improvement](self-improvement.md) di analizzare i fallimenti
dell'agente senza contarci dentro i limiti amministrativi e le attese di un umano.

Le transizioni sono un grafo esplicito: `can_transition` e `validate_transition`
(`durable.py · L111–118`) sollevano `InvalidTransition` invece di lasciar passare una
transizione arbitraria.

---

## Optimistic locking

Ogni scrittura porta `expected_version` e finisce con `WHERE id = ? AND version = ?`.

**Evidenza:** `durable.py · L386–425` (`transition`), `durable.py · L448–461`
(`schedule_retry`).

Se un altro worker ha già toccato l'item, la versione non combacia e la transizione è
rifiutata con `InvalidTransition`. Nessun lock distribuito, nessuna finestra di lettura
stantia.

---

## Idempotenza

`idempotency_key(*parts)` costruisce una chiave stabile da componenti: *«stesse parti →
stessa chiave, side effect una volta sola»* (`durable.py · L120–123`).

### `claim_once`

Il caso d'uso più chiaro. `durable.py · L277–328`:

> «Restituisce `True` se la chiave è nuova (il chiamante procede col side effect), `False` se
> era già stata reclamata — anche in un'esecuzione precedente del backend. È la garanzia
> "una volta sola" che sopravvive al riavvio: due tick nello stesso minuto, o un riavvio
> dentro quel minuto, non fanno scattare due volte lo stesso trigger.»

Due dettagli implementativi che fanno la differenza:

1. **Controllo e inserimento sotto lo stesso lock** — «non c'è finestra fra "esiste?" e
   "inserisci" in cui due chiamate possano entrambe vedere la chiave assente»
   (`durable.py · L294–295`).
2. **L'item viene inserito già in stato `COMPLETED`** — è un marcatore di consumo, non
   lavoro da fare: «uno stato terminale non viene mai reclamato»
   (`durable.py · L308–309`).

È il meccanismo che rende sicuri i [trigger](trigger-autonomi.md).

### Risoluzione degli interrupt

`resolve_interrupt` usa la chiave `run_id + interrupt_id + resolution_version`
(`durable.py · L566–608`): una doppia risposta a un'approvazione — doppio clic, retry di
rete, due tab aperte — non produce due risoluzioni. Se l'interrupt è già risolto, ritorna
lo stato risolto invece di sollevare.

---

## Coda con lease

`claim` reclama la prossima unità disponibile con un lease atomico
(`durable.py · L329–368`): sceglie un item in coda o pronto per retry con `available_at`
passato e senza lease valido, lo porta in `running` con proprietario e scadenza, incrementa
gli attempts. Il `WHERE version = ?` *«rende il claim sicuro contro un secondo worker»*.

`heartbeat` (`durable.py · L369–385`) rinnova il lease durante un lavoro lungo.

### Recupero da worker morto

`reclaim_expired` rimette in coda gli item `running` con lease scaduto
(`durable.py · L465–493`):

> «È il recupero cross-process: nessun run resta bloccato in `running` perché il backend che
> lo teneva è stato riavviato.»

Senza lease, un crash lascerebbe l'item in `running` per sempre. Il lease trasforma «il
worker è morto» in una condizione osservabile e recuperabile.

### Retry con backoff e dead-letter

`schedule_retry` (`durable.py · L427–464`) riporta l'item in coda con `available_at` nel
futuro. Superato `max_attempts` diventa `FAILED` e non viene più reclamato — dead-letter, non
retry infinito.

---

## Interrupt persistiti

Tabella dedicata con indice su `(run_id, status)` (`durable.py · L207–224`).

| Operazione | Evidenza |
|---|---|
| Registrazione | `durable.py · L528–564` |
| Risoluzione idempotente | `durable.py · L566–608` |
| Pendenti globali | `durable.py · L610–617` |
| Pendenti per run | `durable.py · L619–626` |

`all_pending_interrupts` è esposto come `GET /api/durable/interrupts`
(`server.py · L2011–2024`), con una motivazione dichiarata: è *«la prova che gli interrupt
sopravvivono al restart, invece di sparire con le`* strutture in memoria
(`server.py · L2015–2017`).

Una proprietà di durabilità che non si può osservare non si può nemmeno verificare.

---

## Il confine con la memoria

Cosa **non** sopravvive: le `Future` di attesa in `RunManager.approvals` e
`RunManager.interactions`. Dopo un riavvio l'interrupt risulta pendente ma non c'è più
nessuno in attesa di quella risposta: il run va ripreso, non semplicemente approvato.

È il confine esatto tra questa unità e
l'[approvazione](approvazione-azioni-sensibili.md#riavvio-del-processo): qui vive il fatto,
lì viveva l'attesa.

---

## Riepilogo evidenza

| Sito | Righe | Ruolo |
|---|---|---|
| `src/agent_harness/durable.py` | L1–17 | scopo e le due garanzie |
| `src/agent_harness/durable.py` | L32–54 | stati durevoli |
| `src/agent_harness/durable.py` | L107–118 | transizioni validate |
| `src/agent_harness/durable.py` | L120–123 | chiave di idempotenza |
| `src/agent_harness/durable.py` | L185–229 | schema SQLite e indici |
| `src/agent_harness/durable.py` | L277–328 | `claim_once` |
| `src/agent_harness/durable.py` | L329–385 | claim con lease e heartbeat |
| `src/agent_harness/durable.py` | L386–425 | transizione con optimistic locking |
| `src/agent_harness/durable.py` | L427–464 | retry con backoff e dead-letter |
| `src/agent_harness/durable.py` | L465–493 | recupero da lease scaduto |
| `src/agent_harness/durable.py` | L528–626 | interrupt persistiti |
| `src/agent_harness/server.py` | L2011–2024 | endpoint di osservabilità |

**Test:** `tests/test_durable.py`.

---

## Note per chi modifica

- **Ogni scrittura porta `expected_version`.** Una scrittura senza è una regressione della
  prima garanzia, e non fallisce in modo visibile: corrompe silenziosamente in concorrenza.
- **Ogni side effect passa da una idempotency key.** Vale per trigger, creazione run e
  risposte a interrupt.
- **Non collassare gli stati terminali.** Sembrano ridondanti finché non serve distinguere
  «l'agente ha sbagliato» da «è finito il budget» da «aspetta un umano».
- Sostituire lo storage (Postgres/Redis) deve avvenire dietro l'interfaccia di
  `DurableStore`, come previsto a `durable.py · L6–9`.
