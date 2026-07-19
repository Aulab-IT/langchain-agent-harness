# L3 · Continuazione Ralph-style e verifica

**Unità:** stadio 5 → [5.1](../L2_UNITA.md#51--continuazione-ralph-style) e [5.2](../L2_UNITA.md#52--verifica-a-rubric)

*Il run non finisce quando il modello smette di parlare. L'obiettivo viene reiniettato
finché il lavoro non supera i controlli, entro un budget di iterazioni; la difficoltà non si
prevede, si misura, e il modello sale di gradino solo dopo aver fallito.*

Le due unità sono documentate insieme perché condividono lo stesso ciclo: il grader non ha
un grafo proprio, reinietta il feedback nel budget di continuazione.

---

## Il ciclo

**Evidenza:** `runner.py · L200–332`.

```
reset della ladder al gradino basso              L211
prima invocazione                                L212–215
for iteration in 1..harness_max_continuations:   L218
    ├─ controlli euristici                       L232–248
    ├─ se passano e c'è testo → grader           L256–258
    │     └─ grade.passed → RETURN completed     L259–266
    ├─ ultima iterazione → RETURN non completato  L278–288
    ├─ scelta del prompt di continuazione        L289–311
    ├─ escalation SE fallimento netto            L314
    └─ reinvocazione con l'obiettivo             L330–333
```

Ogni obiettivo riparte dal gradino più economico: *«l'escalation vale per un obiettivo, non
per la sessione. Un compito difficile non rende caro quello che viene dopo»*
(`runner.py · L209–211`).

---

## Cosa impedisce a `[GOAL_COMPLETE]` di chiudere un run

Il marcatore da solo non basta. Prima passano i controlli euristici, poi il grader.

### Verifica d'ambiente

Se l'obiettivo contiene un verbo di produzione, serve una prova d'esecuzione riuscita.

**Evidenza:** `runner.py · L53–77`.

I verbi coprono **entrambe le lingue** del progetto, con la motivazione scritta accanto:
«come il router, non privilegia l'italiano — `write a report` e `scrivi un report` devono
comportarsi allo stesso modo» (`runner.py · L52–55`).

La prova è un `ToolMessage` di `docker_exec` con `exit_code=0`
(`runner.py · L93–103`), oppure una verifica delegata a un subagente
(`runner.py · L125–127`).

### Il taglio al turno corrente

Il dettaglio più facile da rompere in un refactor:

```python
def _current_turn_messages(messages):
    """Senza questo taglio, un `docker_exec` andato a buon fine in un obiettivo
    precedente dello stesso thread soddisferebbe la verifica dell'obiettivo
    attuale — l'intera storia del thread è visibile qui."""
```

**Evidenza:** `runner.py · L80–91`.

La verifica cerca solo tra i messaggi successivi all'ultimo `HumanMessage`. Senza,
il primo obiettivo verificato di un thread renderebbe «verificati» tutti quelli dopo.

### Controlli estensibili

Oltre a quello d'ambiente, il runner esegue i `completion_checks` registrati sull'harness
(`runner.py · L245–246`), definiti in `outcome_checks.py`. Ogni check ritorna
`(passato, messaggio)` e i messaggi dei falliti diventano feedback per l'iterazione
successiva.

---

## Grader a rubric

Chiamato solo se i controlli euristici passano **e** c'è testo (`runner.py · L256`): non si
paga una valutazione per un output che è già stato scartato.

L'esito distingue tre casi, non due — ed è la parte più fine dell'unità.

**Evidenza:** `runner.py · L252–277`.

| Esito | Cosa succede |
|---|---|
| `grade.passed` | run completato |
| sotto la soglia di uscita, sopra quella di escalation | **riprova con lo stesso modello** |
| sotto la soglia di escalation | riprova con il gradino superiore |

Il commento spiega perché: *«Un punteggio sotto la soglia di uscita fa riprovare; solo un
punteggio sotto la soglia di escalation dice che il gradino non ce la fa. Fra le due,
l'agente riprova con lo stesso modello: costa una iterazione economica invece che una cara»*
(`runner.py · L252–254`).

### Retry della sola risposta

Caso particolare: il lavoro è stato fatto (c'è evidenza di completamento) e il grader non ha
segnalato problemi di **sicurezza** né di **aderenza** — entrambi i criteri ≥ 0.5. Allora il
problema è la risposta finale, non il lavoro.

**Evidenza:** `runner.py · L270–277`.

In quel caso `fallimento_netto` resta falso — niente escalation — e la continuazione usa
`FINAL_RESPONSE_FEEDBACK_PROMPT` invece del prompt di verifica generico
(`runner.py · L290–301`). Si chiede di riscrivere la risposta, non di rifare il lavoro.

I due criteri esclusi dal retry-leggero non sono casuali: sicurezza e aderenza sono quelli
per cui «rispondi meglio» non è mai la correzione giusta.

---

## Escalation misurata

```python
salito = self.harness.ladder.escalate() if fallimento_netto else False
```

**Evidenza:** `runner.py · L312–314`.

Il commento è la tesi dell'unità: *«Il gradino ha fallito nettamente: la continuazione la fa
il gradino sopra. È il cuore dell'escalation: non si prevede la difficoltà, la si misura»*.

Nessuna euristica prova a indovinare dal testo dell'obiettivo se serve un modello forte. Si
parte dal basso, e si sale solo dopo un fallimento osservato. L'evento `model.escalated`
finisce nella trace (`runner.py · L316–323`).

---

## Esiti terminali

**Evidenza:** `runner.py · L279–288`.

| `terminal_status` | Quando |
|---|---|
| `completed` | controlli passati e grader passato |
| `failed_verification` | budget esaurito **dopo** almeno un fallimento di verifica |
| `incomplete` | budget esaurito senza fallimenti di verifica |

La distinzione tra gli ultimi due è ciò che permette al ciclo di self-improvement di non
contare come «errore dell'agente» un run semplicemente troppo lungo.
`failure_reason` porta il motivo dell'ultimo fallimento.

---

## Casi limite

### Confine tra iterazioni

L'evento `assistant.iteration` esiste per un motivo di interfaccia: *«la UI accumula i delta
di streaming e senza questo marcatore concatenerebbe la risposta di ogni continuazione alla
precedente»* (`runner.py · L326–328`).

### Limiti di sicurezza

- Obiettivo: 1–20.000 caratteri (`runner.py · L201–203`).
- `recursion_limit: 200` sul grafo (`runner.py · L205–207`).
- Budget di continuazione: `harness_max_continuations`.

### Stato impossibile

Il ciclo termina con `raise AssertionError("Ciclo di continuazione terminato in stato
impossibile.")` (`runner.py · L333`). Non è codice morto difensivo generico: rende rumoroso
un eventuale futuro `break` che saltasse i due `return`.

---

## Riepilogo evidenza

| Sito | Righe | Ruolo |
|---|---|---|
| `src/agent_harness/runner.py` | L45–50 | estrazione del testo finale |
| `src/agent_harness/runner.py` | L53–77 | verbi bilingue e trigger di verifica |
| `src/agent_harness/runner.py` | L80–91 | taglio al turno corrente |
| `src/agent_harness/runner.py` | L93–103 | prova d'esecuzione riuscita |
| `src/agent_harness/runner.py` | L200–215 | avvio, reset ladder, limiti |
| `src/agent_harness/runner.py` | L233–250 | controlli euristici e feedback |
| `src/agent_harness/runner.py` | L252–277 | grader, tre esiti, retry leggero |
| `src/agent_harness/runner.py` | L279–288 | esiti terminali |
| `src/agent_harness/runner.py` | L290–311 | scelta del prompt di continuazione |
| `src/agent_harness/runner.py` | L312–328 | escalation misurata ed eventi |
| `src/agent_harness/runner.py` | L335–387 | invocazione del grader |
| `src/agent_harness/verification.py` | — | `RubricGrader`, rubric congelata |
| `src/agent_harness/outcome_checks.py` | — | check di completamento |
| `src/agent_harness/prompts.py` | — | i tre prompt di continuazione |

**Test:** `tests/test_runner.py`, `tests/test_verification.py`, `tests/test_outcome_checks.py`.

---

## Note per chi modifica

- **Non togliere `_current_turn_messages`.** È l'unica cosa che impedisce a una verifica
  vecchia di validare un obiettivo nuovo nello stesso thread.
- **Aggiungere un check** → `outcome_checks.py`, con la firma `(goal, messages) →
  (passato, messaggio)`. Il messaggio diventa feedback: scrivilo come istruzione, non come
  diagnosi.
- **Non anticipare l'escalation con euristiche sul testo.** Il progetto ha scelto
  deliberatamente di misurare invece di prevedere.
- La rubric e la soglia sono **congelate** rispetto al ciclo di self-improvement: sono
  fuori dalla whitelist degli override apposta, altrimenti l'agente potrebbe abbassare
  l'asticella che lo valuta.
