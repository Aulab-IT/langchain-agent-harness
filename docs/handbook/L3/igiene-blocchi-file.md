# L3 · Igiene dei blocchi-file verso il provider

**Unità:** stadio 3 · esecuzione del turno → [3.1](../L2_UNITA.md#31--igiene-dei-blocchi-file-verso-il-provider)

*Prima di ogni chiamata al modello, i blocchi-file allegati alla conversazione vengono
ispezionati: quelli palesemente corrotti sono sostituiti con una nota testuale, così un
singolo file malformato non rende la conversazione irrecuperabile.*

Unità piccola, ma è il caso di studio migliore del manuale su una cosa: **un comportamento
può esistere per proteggere l'harness da sé stesso**, e la sua ragione d'essere non è
deducibile dal codice senza il commento che la spiega.

---

## Il problema che risolve

Quando l'agente legge un file binario, deepagents lo allega alla conversazione come blocco
multimodale `{"type": "file"|"image", "base64": ..., "mime_type": ...}` così il modello può
"vederlo".

Se quel file non è valido — un PDF finto di pochi byte scritto per errore da un modello
debole — il provider rifiuta l'**intera richiesta** con un 400 `invalid_file`. E poiché il
blocco resta nella storia del thread, **ogni chiamata successiva lo rimanda**: la
conversazione diventa irrecuperabile, e ogni «riprova» muore sul nascere.

**Evidenza:** `file_guard.py · L1–14` (docstring del modulo).

Il fallimento non è nel file: è nel fatto che l'errore è *persistente e auto-riproducente*.
Senza questa guardia, l'unico rimedio è buttare il thread.

---

## Trigger

Non una tool call: **ogni chiamata al modello**. È un middleware che avvolge la richiesta.

**Evidenza:** `file_guard.py · L82–102` (`FileBlockGuardMiddleware`), registrato in
`factory.py · L982`.

Implementa entrambe le versioni, sincrona e asincrona (`wrap_model_call` e
`awrap_model_call`), con la stessa logica: sanifica, e se qualcosa è cambiato sostituisce i
messaggi della richiesta prima di passarla all'handler.

---

## Regola di validazione

```python
_MAGIC: dict[str, bytes] = {
    "application/pdf": b"%PDF",
}
```

**Evidenza:** `file_guard.py · L30–33`.

Un blocco è corrotto se **dichiara un mime che sappiamo validare** e il suo contenuto non
ne ha la firma. Tre casi:

| Caso | Esito | Evidenza |
|---|---|---|
| mime non in `_MAGIC` | passa invariato | `file_guard.py · L44–46` |
| base64 illeggibile | **corrotto** — il provider lo rifiuterebbe comunque | `file_guard.py · L47–52` |
| firma diversa da quella attesa | corrotto | `file_guard.py · L53` |

La tabella ha una sola voce oggi. È deliberato: la guardia valida ciò che sa validare e
lascia passare il resto invariato. Non prova a indovinare.

Il sostituto è una nota testuale:
`[file non valido rimosso: il contenuto non corrisponde al tipo dichiarato]`
(`file_guard.py · L35`). Il modello vede una spiegazione, non un buco.

---

## Efficienza deliberata

`sanitize_messages` tocca **solo** i messaggi che contengono almeno un blocco corrotto; gli
altri passano per riferimento, così non si ricostruisce l'intera lista a ogni chiamata
(`file_guard.py · L56–60`). Il middleware gira su ogni turno di ogni run: il costo del caso
normale — nessun blocco corrotto — deve essere prossimo a zero.

Stessa logica nel middleware: `request.override(...)` viene chiamato solo `if cleaned`
(`file_guard.py · L88–90`).

---

## Percorsi di eccezione

La decodifica base64 è protetta con un `except Exception` che classifica il blocco come
corrotto invece di sollevare (`file_guard.py · L47–51`). Scelta corretta per una guardia: un
input che non riesce nemmeno a essere ispezionato è esattamente il tipo di input che non
deve raggiungere il provider.

Non esiste un percorso in cui questa unità faccia fallire il run. Al massimo rimuove
qualcosa.

---

## Riepilogo evidenza

| Sito | Righe | Ruolo |
|---|---|---|
| `src/agent_harness/file_guard.py` | L1–14 | il problema e perché è persistente |
| `src/agent_harness/file_guard.py` | L30–35 | firme note e nota sostitutiva |
| `src/agent_harness/file_guard.py` | L39–53 | rilevamento del blocco corrotto |
| `src/agent_harness/file_guard.py` | L56–79 | sanificazione con copia minima |
| `src/agent_harness/file_guard.py` | L82–102 | middleware sync e async |
| `src/agent_harness/factory.py` | L982 | registrazione nella pila di middleware |

**Test:** `tests/test_file_guard.py` — logica pura sui messaggi, testabile offline senza
chiamare nessun provider.

---

## Note per chi modifica

- **Aggiungere un formato** → basta una voce in `_MAGIC` (`file_guard.py · L30–33`), purché
  il formato abbia una firma iniziale stabile. Se non ce l'ha, non aggiungerlo: un falso
  positivo qui cancella un allegato valido.
- **Non trasformarla in validazione completa.** Lo scopo è impedire il 400 auto-riproducente,
  non garantire che il file sia corretto. Un PDF con firma giusta e contenuto rotto passa, e
  va bene: il provider lo accetta.
- Il middleware deve restare economico sul caso normale: qualunque refactor che copi sempre
  la lista dei messaggi è una regressione, non un dettaglio.
