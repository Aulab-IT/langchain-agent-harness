# L3 · Trigger autonomi

**Unità:** trasversale → [T.2](../L2_UNITA.md#t2--trigger-autonomi)

*Un run può partire senza nessuno davanti allo schermo: a orario (cron) o su evento
(webhook). Lo stesso trigger non scatta due volte per lo stesso istante, nemmeno attraverso
un riavvio, e il payload di un webhook è sempre dato, mai istruzione.*

Il rischio dell'esecuzione autonoma è duplice: **eseguire due volte** e **farsi comandare
da chi manda l'evento**. L'unità affronta entrambi esplicitamente.

---

## Cron

### Valutazione dell'espressione

`cron_matches` (`triggers.py · L53–83`) su cinque campi standard, con `_match_field`
(`triggers.py · L18–42`) che gestisce liste (`,`), intervalli (`-`), step (`/`) e wildcard
(`*`, `?`).

I valori fuori dai limiti del campo vengono **saltati**, non fatti esplodere
(`triggers.py · L35–36`): un'espressione parzialmente sbagliata non fa scattare a caso.

`resolve_timezone` (`triggers.py · L45–51`) risolve il fuso; `next_runs`
(`triggers.py · L84–101`) e `describe_cron` (`triggers.py · L110–136`) servono
all'anteprima nella UI — si vede cosa farà prima di salvarlo.

### La chiave anti-doppio-fire

Due difese in serie, con ruoli diversi.

**Evidenza:** `triggers.py · L161–199`.

```python
minute_key = moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M")
```

La chiave è **in UTC**, e il commento dice perché: *«indipendente dal fuso del singolo
trigger, e immune ai salti dell'ora legale, che nel fuso locale ripetono lo stesso minuto»*
(`triggers.py · L165–166`).

Il caso è concreto: alla fine dell'ora legale, l'ora locale 02:30 accade due volte. Con una
chiave in fuso locale, un cron delle 02:30 scatterebbe due volte quella notte. In UTC il
problema non esiste.

| Difesa | Cosa copre | Evidenza |
|---|---|---|
| cache in memoria `_fired_minutes` | doppio tick nello stesso minuto | `triggers.py · L187–188` |
| `claim_fire` durevole | riavvio dentro lo stesso minuto | `triggers.py · L189–195` |

Il commento nel costruttore è netto: la cache *«è la prima linea (veloce); questo è la
garanzia "una volta sola" che sopravvive al riavvio — senza, un restart dentro lo stesso
minuto rifà scattare il cron»* (`triggers.py · L153–156`).

`claim_fire` è cablato su `claim_once` del [lavoro durevole](lavoro-durevole.md#claim_once).

La cache viene **potata a ogni tick**, tenendo solo il minuto corrente: «le voci dei minuti
passati non hanno più effetto e crescerebbero senza limite» (`triggers.py · L168–169`). Una
cache anti-duplicato che cresce all'infinito è una perdita di memoria travestita da
ottimizzazione.

### Robustezza del loop

Ogni livello cattura e continua:

- cron o fuso non validi → warning, si salta quel trigger (`triggers.py · L180–186`);
- `on_fire` che solleva → exception loggata, gli altri trigger proseguono
  (`triggers.py · L197–199`);
- tick che fallisce → loggato, il loop continua (`triggers.py · L202–208`).

Un trigger rotto non ferma lo scheduler.

---

## Webhook

### Autenticazione per token

`POST /api/triggers/{trigger_id}/webhook` (`server.py · L2673–2719`). Il token può stare
nell'header `X-Trigger-Token` o come parametro, per essere chiamabile da `curl` e da sistemi
che non impostano header.

Il commento sul CORS chiarisce il modello di sicurezza: i webhook *«sono autenticati dal
token, non dall'origine: sono pensati per essere chiamati»* da qualunque origine
(`server.py · L1907–1910`, `server.py · L2633–2639`). Il preflight aperto non è una svista:
è la conseguenza coerente dell'aver scelto il token come unico fattore.

### Il payload è dato, mai istruzione

**Evidenza:** `server.py · L1749–1754`.

> «Costruisce il goal del run; il payload webhook è allegato come dato **NON attendibile**.»

È la difesa contro la prompt injection via webhook. Chiunque conosca l'URL e il token può
mandare un JSON; se quel JSON finisse nel prompt come istruzione, il trigger diventerebbe un
canale di comando remoto verso l'agente.

### Sessione fresca a ogni evento

```
fresh_each_fire = trigger.get("kind") == "webhook"
```

**Evidenza:** `server.py · L1772–1779`.

I webhook aprono una sessione nuova a ogni evento. Due conseguenze: un evento non vede il
contesto di quello precedente (nessun accumulo di payload non attendibili nello stesso
thread), e due eventi concorrenti non si mescolano.

I cron, invece, mantengono la sessione — sono lavoro ricorrente dello stesso tipo, e la
continuità è utile.

---

## Riepilogo evidenza

| Sito | Righe | Ruolo |
|---|---|---|
| `src/agent_harness/triggers.py` | L18–42 | valutazione di un campo cron |
| `src/agent_harness/triggers.py` | L45–83 | fuso orario e match completo |
| `src/agent_harness/triggers.py` | L84–136 | anteprima e descrizione |
| `src/agent_harness/triggers.py` | L138–160 | scheduler e reclamo durevole |
| `src/agent_harness/triggers.py` | L161–200 | chiave UTC, doppia difesa, potatura |
| `src/agent_harness/triggers.py` | L202–222 | loop resiliente e avvio/stop |
| `src/agent_harness/server.py` | L1749–1754 | payload come dato non attendibile |
| `src/agent_harness/server.py` | L1772–1779 | sessione fresca per i webhook |
| `src/agent_harness/server.py` | L2633–2639 | preflight CORS aperto |
| `src/agent_harness/server.py` | L2673–2719 | endpoint webhook con token |
| `src/agent_harness/durable.py` | L277–328 | garanzia «una volta sola» |

**Test:** `tests/test_triggers.py`, `tests/test_server.py`.

---

## Note per chi modifica

- **Non spostare la chiave anti-doppio-fire nel fuso locale.** Il bug ricompare una notte
  all'anno, che è il modo peggiore di scoprirlo.
- **Non rimuovere `claim_fire`** lasciando solo la cache in memoria: la garanzia si riduce
  alla vita del processo.
- **Non promuovere il payload webhook a istruzione**, in nessuna forma — nemmeno «solo il
  campo `goal`». Il canale è aperto per costruzione.
- Se un trigger deve poter influenzare *cosa* fa l'agente, la strada è un parametro
  tipizzato e validato lato harness, non testo libero che entra nel prompt.
