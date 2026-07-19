# L3 · Azione utente sbloccante

**Unità:** stadio 4 · esecuzione guardata → [4.2](../L2_UNITA.md#42--azione-utente-sbloccante)

*Quando l'agente è bloccato su qualcosa che solo un umano può fare nel mondo reale — dare
un consenso OAuth nel browser, incollare un token, caricare un file di credenziali,
completare un 2FA — sospende il run, mostra istruzioni passo-passo, e riprende con il
valore ottenuto.*

Da non confondere con l'[approvazione](approvazione-azioni-sensibili.md): lì l'agente
chiede **permesso** per un'azione che sa fare; qui chiede **collaborazione** per un'azione
che non può fare.

---

## Trigger

Il modello chiama il tool `request_user_action`, esposto con uno schema tipizzato che lo
costringe a dire cosa vuole indietro.

**Evidenza:** `interaction.py · L79–93` (definizione del tool), `interaction.py · L21–47` (schema).

| Campo | Vincolo | Ruolo |
|---|---|---|
| `title` | 1–200 char | titolo breve dell'azione |
| `instructions` | 1–6.000 char, markdown | passi concreti: cosa aprire, cliccare, incollare |
| `response_kind` | `confirm` \| `value` \| `file` | **cosa deve tornare indietro** |
| `url` | max 2.000 char, opzionale | link da aprire (es. consenso OAuth) |

`response_kind` è il campo che struttura il comportamento: determina cosa la UI mostra e
come il risultato viene reinterpretato per il modello.

La descrizione del tool delimita esplicitamente lo scopo: è «l'ultimo miglio» — le chiamate
di rete l'agente le fa da solo con `docker_exec with_network=true`, non chiedendole
all'utente (`interaction.py · L83–91`).

---

## Percorso di esecuzione

`request_user_action` chiama `interrupt()` di LangGraph con un payload marcato
`"type": "user_action"` (`interaction.py · L57–65`). È quel marcatore a discriminare il
ramo nel loop del runner (`runner.py · L169–174`):

```
"__interrupt__" in result
  ├─ payload["type"] == "user_action" → interaction_callback → Command(resume=response)
  └─ altrimenti                        → approval_callback   (unità 4.1)
```

I due rami sono nello stesso `while` ma non condividono nulla oltre a esso: callback
diversi, stato diverso, timeout diversi, endpoint diversi.

---

## Traduzione della risposta

Il valore che torna dall'utente non arriva grezzo al modello: viene tradotto in una frase
che dice all'agente *cosa fare dopo*.

**Evidenza:** `interaction.py · L66–76`.

| Risposta | Cosa vede il modello |
|---|---|
| `{"cancelled": True}` | «L'utente ha annullato l'azione richiesta: **non procedere oltre su questo percorso**» |
| `{"response": <valore>}` | «L'utente ha completato l'azione. Valore fornito: `<valore>`» |
| conferma senza valore | «L'utente ha confermato di aver completato l'azione richiesta» |

L'annullamento non è un errore: è un'istruzione. La frase è scritta per impedire che
l'agente reinterpreti il rifiuto come «riprova in altro modo» e insista sullo stesso
percorso bloccato.

---

## Cambi di stato

| Momento | Cosa cambia | Evidenza |
|---|---|---|
| Sospensione | run → `waiting_action` (non `waiting_approval`) | `server.py · L1243` |
| Sospensione | interrupt durevole di tipo `user_action` | `server.py · L1244` |
| Sospensione | notifica «serve un'azione da te» | `server.py · L1245–1250` |
| Sospensione | evento `action.requested` | `server.py · L1251` |
| Risoluzione | interrupt risolto, run → `running` | `server.py · L1258–1259` |
| Annullamento | `terminal_hint = "blocked_needs_human"` | `server.py · L1266–1268` |

L'ultimo è il più interessante per chi verifica: un run annullato qui non finisce come
«fallito» generico ma come **bloccato in attesa di un umano**, con una motivazione
esplicita. Distinzione che conta per le statistiche del ciclo di self-improvement, che
altrimenti conterebbe come errore dell'agente qualcosa che errore non è.

---

## Casi limite

### L'autonomia non si applica

Il commento nel codice è netto: *«si attende SEMPRE l'utente (l'autonomia non può svolgere
un'azione reale come un consenso OAuth nel browser)»* (`server.py · L1232–1233`).

Non esiste un ramo di auto-risoluzione. È una differenza sostanziale rispetto a 4.1, dove
la modalità autonoma salta le approvazioni locali: qui non c'è niente da saltare, perché
non c'è nessuna decisione da prendere — c'è un'azione fisica che manca.

### Timeout lungo

**1.800 secondi**, trenta minuti (`server.py · L1254`), contro i 600 dell'approvazione. La
proporzione riflette il compito: approvare è un clic, completare un flusso OAuth su un
altro dispositivo no. Alla scadenza il risultato è `{"cancelled": True}` — stessa strada
dell'annullamento esplicito.

### Troncamento difensivo

Il control plane ritronca `title` e `instructions` ai limiti dello schema
(`server.py · L1235–1240`) anche se `UserActionInput` li ha già validati. Ridondanza
deliberata: il payload che arriva alla UI non dipende dalla fiducia in un validatore a
monte.

### Nessun callback

`RuntimeError("Azione utente richiesta ma manca il callback.")` (`runner.py · L170–171`).
Come per 4.1: senza superficie di interazione, il run si ferma invece di proseguire alla
cieca.

### Annullamento del run

`cancel` completa anche la future di interazione con `{"cancelled": True}`, non solo quella
di approvazione (`server.py · L1714–1716`).

---

## Riepilogo evidenza

| Sito | Righe | Ruolo |
|---|---|---|
| `src/agent_harness/interaction.py` | L21–47 | schema tipizzato dell'input |
| `src/agent_harness/interaction.py` | L50–76 | interrupt e traduzione della risposta |
| `src/agent_harness/interaction.py` | L79–93 | esposizione come tool |
| `src/agent_harness/runner.py` | L169–174 | ramo dedicato nel loop di sospensione |
| `src/agent_harness/server.py` | L1231–1269 | callback, stato, timeout, hint terminale |
| `src/agent_harness/server.py` | L1700–1706 | risoluzione dal REST |
| `src/agent_harness/server.py` | L2551–2555 | endpoint `POST /api/runs/{id}/action` |
| `client/src/components/shared/UserActionDialog.tsx` | L1–184 | modale con istruzioni e input |
| `client/src/App.tsx` | L241–245 | montaggio del modale |

**Test:** `tests/test_interaction.py`, `tests/test_runner.py`, `tests/test_server.py`.

---

## Note per chi modifica

- **Aggiungere un `response_kind`** → `interaction.py · L18` più la traduzione a
  `L66–76` e il rendering in `UserActionDialog.tsx`. Tre siti, nessuno opzionale.
- **Non aggiungere auto-risoluzione.** Se qualcuno chiede «in autonomia salta anche
  questo», la risposta è che non c'è niente da saltare: il valore che serve non esiste
  finché un umano non lo produce.
- L'hint `blocked_needs_human` è consumato a valle dalle statistiche: cambiarne la stringa
  richiede di seguirla fino a `outcome_checks.py` e alla vista Miglioramenti.
