# Step 16 — Esecuzione durevole

## Obiettivo

Fare sopravvivere run e approvazioni a retry, doppio invio e riavvio del processo. Un task async
tenuto solo in RAM non basta: dopo un crash non sappiamo se il lavoro fosse iniziato, terminato o
in attesa di una persona.

## Meccanismi

La state machine distingue esiti semanticamente diversi: completato, incompleto, verifica fallita,
budget esaurito, stop di sicurezza e attesa umana. Transizioni invalide vengono rifiutate. La chiave
di idempotenza impedisce di accodare due volte la stessa richiesta.

Un worker prende un item con lease temporaneo. Se muore, il lease scade e un altro worker può
recuperarlo. Il version counter realizza optimistic locking: un worker con stato obsoleto non può
sovrascrivere il risultato di uno più recente. Gli interrupt HITL vivono nello stesso database e
la loro risoluzione è idempotente.

## Esecuzione

```bash
uv run python steps/16_durable_execution/app.py
```

Lo script chiude e riapre SQLite tra richiesta di approvazione e decisione. Il pending interrupt
resta disponibile. Prova a ripetere la risoluzione con una decisione diversa: la prima resta valida.

## Limite

Durabilità non significa exactly-once per effetti esterni. Email, deploy e pagamenti richiedono una
chiave idempotente anche nel sistema remoto.
