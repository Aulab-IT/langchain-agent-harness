# Harness Handbook — questo progetto

Manuale a livello di *comportamento* dell'harness. Non descrive i moduli uno per uno
(quello lo fa già [`../HARNESS_COMPONENTS.md`](../HARNESS_COMPONENTS.md)): descrive **cosa
succede quando l'agente prova a fare qualcosa**, e per ogni affermazione indica il punto
esatto del codice che la rende vera.

Il metodo è quello di [Harness Handbook](https://ruhan-wang.github.io/Harness-Handbook)
(Tencent HY LLM Frontier, 2026), applicato a un harness piccolo — ~40 moduli invece dei
2.267 file di Codex — quindi la mappa è scritta a mano e verificata a mano, senza pipeline
di estrazione automatica.

## Perché serve

Un comportamento non vive in un file. Prendi «chiedi conferma prima di eseguire un comando
in sandbox»: per capirlo davvero devi tenere insieme la policy che decide *quando* fermarsi
(`factory.py`), il loop che gestisce la sospensione (`runner.py`), la redazione del payload
mostrato all'utente (`server.py`), la persistenza dell'interrupt (`durable.py`), la
classificazione del comando (`command_review.py`) e il modale che raccoglie la risposta
(`ApprovalDialog.tsx`). Sei file, due linguaggi, un solo comportamento.

La documentazione per componente ti dice dove sono i pezzi. Questo manuale ti dice come si
compongono.

## I tre livelli

| Livello | Domanda a cui risponde | File |
|---|---|---|
| **L1 · Sistema** | Come gira l'harness nel suo insieme? Quali stadi attraversa una richiesta? | [`L1_SISTEMA.md`](L1_SISTEMA.md) |
| **L2 · Unità di comportamento** | Quale unità governa il comportamento che mi interessa? Da cosa dipende? | [`L2_UNITA.md`](L2_UNITA.md) |
| **L3 · Dettaglio** | Quali sono trigger, cambi di stato, percorsi di eccezione, casi limite — e dove sta scritto? | [`L3/`](L3/) |

## Come si naviga (BGPD)

*Behavior-Guided Progressive Disclosure*: parti dalla domanda, non dal file.

```
domanda di comportamento
  → L1  (in quale stadio del flusso cade?)
  → L2  (quale unità la governa? cosa la circonda?)
  → L3  (trigger, stato, percorsi, casi limite)
  → evidenza nel codice (file · righe)
```

Tre usi dello stesso percorso:

- **Capire** — fermati a L1+L2. Ti costruisci il modello del sistema prima di aprire un file.
- **Verificare** — scendi a L3. Controlla che ogni percorso di esecuzione, compresi i
  fallback e i casi limite, rispetti la policy dichiarata.
- **Modificare** — usa L3 per delimitare il confine della modifica: quali siti di
  implementazione devi toccare e quali invarianti non puoi rompere.

## Le unità

Quindici unità di comportamento, tutte con il dettaglio L3 e l'evidenza nel codice.

| # | Unità di comportamento | Stadio | Dettaglio |
|---|---|---|---|
| 1.1 | Confinamento del filesystem | configurazione | [L3](L3/confinamento-filesystem.md) |
| 1.2 | Registry dei provider e ladder dei modelli | configurazione | [L3](L3/registry-provider-e-ladder.md) |
| 2.1 | Budget di contesto e compaction | contesto | [L3](L3/budget-di-contesto.md) |
| 2.2 | Progressive disclosure delle skill | contesto | [L3](L3/progressive-disclosure-skill.md) |
| 3.1 | Igiene dei blocchi-file verso il provider | turno | [L3](L3/igiene-blocchi-file.md) |
| 4.1 | Approvazione di azioni sensibili (HITL) | esecuzione guardata | [L3](L3/approvazione-azioni-sensibili.md) |
| 4.2 | Azione utente sbloccante | esecuzione guardata | [L3](L3/azione-utente-sbloccante.md) |
| 4.3 | Esecuzione in sandbox | esecuzione guardata | [L3](L3/esecuzione-in-sandbox.md) |
| 5.1–5.2 | Continuazione Ralph-style e verifica a rubric | continuazione | [L3](L3/continuazione-e-verifica.md) |
| 5.3 | Budget di run | continuazione | [L3](L3/budget-di-run.md) |
| 6.1 | Lavoro durevole | persistenza | [L3](L3/lavoro-durevole.md) |
| 6.2 | Contratto di evidenza e gate di delivery | persistenza | [L3](L3/evidenza-e-delivery-gate.md) |
| T.1 | Delega a subagenti | trasversale | [L3](L3/delega-a-subagenti.md) |
| T.2 | Trigger autonomi | trasversale | [L3](L3/trigger-autonomi.md) |
| T.3 | Ciclo di self-improvement | trasversale | [L3](L3/self-improvement.md) |

### Percorsi di lettura suggeriti

**Il percorso di un comando pericoloso**, dall'intenzione all'effetto:
[4.1 approvazione](L3/approvazione-azioni-sensibili.md) →
[4.3 sandbox](L3/esecuzione-in-sandbox.md) →
[6.2 evidenza](L3/evidenza-e-delivery-gate.md).

**Cosa impedisce a un run di costare troppo:**
[2.1 contesto](L3/budget-di-contesto.md) →
[5.3 budget di run](L3/budget-di-run.md) →
[5.1 continuazione](L3/continuazione-e-verifica.md).

**Cosa regge a un riavvio del backend:**
[6.1 lavoro durevole](L3/lavoro-durevole.md) →
[T.2 trigger](L3/trigger-autonomi.md).

**Cosa impedisce all'agente di allargarsi:**
[1.1 filesystem](L3/confinamento-filesystem.md) →
[T.1 subagenti](L3/delega-a-subagenti.md) →
[T.3 self-improvement](L3/self-improvement.md).

## Regole di scrittura

Chi aggiunge un'unità L3 rispetta queste regole, altrimenti il manuale smette di essere
affidabile e diventa prosa:

1. **Ogni affermazione ha un'evidenza.** Formato `<percorso> · L<inizio>–<fine>`. Nessuna
   eccezione. Il test `tests/test_handbook_anchors.py` verifica che ogni ancora punti a un
   file esistente e a righe che esistono davvero.
2. **I riferimenti si verificano.** Le righe si spostano: prima di un commit che tocca un
   sito citato, ricontrolla l'ancora. Se una riga non torna, il manuale è rotto, non
   «leggermente datato».
3. **I casi limite non sono opzionali.** La sezione più utile a chi verifica è quella che
   dice cosa succede in modalità autonoma, dopo un riavvio, in caso di timeout, quando il
   run viene annullato a metà.
4. **La prosa spiega, i fatti ancorano.** Se una frase non è verificabile aprendo il codice
   citato, riscrivila o toglila.
