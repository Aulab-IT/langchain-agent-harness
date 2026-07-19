# L3 · Budget di contesto e compaction

**Unità:** stadio 2 · assemblaggio del contesto → [2.1](../L2_UNITA.md#21--budget-di-contesto-e-compaction)

*La finestra di contesto è un limite realmente applicato, non un metadato mostrato in UI. A
ogni ispezione l'harness misura quanto è piena, sceglie l'azione minima sufficiente a
rientrare, e la esegue in un secondo momento.*

---

## Decisione separata dall'esecuzione

Il pilastro dell'unità sta nel docstring di `ContextBudgetManager`: *«Ispeziona il contesto e
decide l'azione, senza eseguirla. Separare la decisione dall'esecuzione rende la politica
testabile in isolamento e permette al runner di emettere l'azione come evento prima di
applicarla»* (`context_budget.py · L110–115`).

Conseguenza pratica: puoi verificare l'intera politica di compaction con test offline che
non chiamano nessun modello e non toccano nessun file. `inspect` produce un
`ContextSnapshot`, `decide` mappa snapshot → azione, e basta.

---

## Le soglie

`ContextBudget` (`context_budget.py · L39–88`):

| Campo | Default | Significato |
|---|---|---|
| `max_tokens` | da `Settings` | finestra del modello |
| `reserved_output_tokens` | 4.000 | spazio tenuto libero per la risposta |
| `warning_ratio` | 0.7 | zona di allerta |
| `compaction_ratio` | 0.8 | si riduce davvero |
| `hard_ratio` | 0.95 | ultima risorsa |

I rapporti sono frazioni della **finestra utile** (`max_tokens - reserved_output_tokens`),
non della finestra totale (`context_budget.py · L54–58`, `context_budget.py · L86–88`).
Se non fosse così, all'80% di riempimento non ci sarebbe abbastanza spazio per la
risposta.

`context_budget_from_settings` collega il tutto alla configurazione, con l'intento
dichiarato di *«rendere `harness_context_window` un limite realmente applicato invece di un
semplice metadato mostrato in UI»* (`context_budget.py · L305–313`).

---

## La scala delle azioni

`ContextAction` è ordinata per aggressività crescente (`context_budget.py · L28–37`):

```
KEEP
  → OFFLOAD_TOOL_OUTPUT          recupero grande, informazione persa zero
    → SUMMARIZE_HISTORY          si perdono le chiacchiere, non i fatti
      → DROP_RECONSTRUCTIBLE_EVENTS
        → START_FRESH_CONTINUATION
          → REJECT_OVER_BUDGET   solo se il prompt di sistema da solo sfora
```

`decide` sceglie **l'azione minima sufficiente** (`context_budget.py · L146–177`):

| Condizione | Azione |
|---|---|
| `ratio < warning` | `KEEP` |
| zona warning, c'è materiale offloadabile | `OFFLOAD_TOOL_OUTPUT` |
| zona warning, niente da recuperare | `KEEP` — non si interviene per il gusto di farlo |
| oltre `compaction`, c'è materiale offloadabile | `OFFLOAD_TOOL_OUTPUT` |
| oltre `compaction`, storia > metà finestra utile | `SUMMARIZE_HISTORY` |
| oltre `hard_ratio`, niente di comprimibile | `START_FRESH_CONTINUATION` |
| oltre `hard_ratio`, storia sotto il pavimento | `REJECT_OVER_BUDGET` |

Due commenti nel codice spiegano le scelte non ovvie:

- In zona warning si interviene **solo se c'è un recupero facile** (`context_budget.py · L158`).
  Riassumere costa una chiamata al modello: non si paga finché non serve.
- La continuazione fresca è preferita al rifiuto perché *«meglio una continuazione fresca
  che sbattere contro il rifiuto del provider a metà run»* (`context_budget.py · L168–169`).

Il rifiuto è l'unico esito senza uscita, e scatta solo quando non c'è letteralmente niente
da comprimere.

### Le soglie devono restare ordinate

`decide` confronta le soglie **in sequenza**, quindi il loro ordine è un presupposto della
politica, non una convenzione. `__post_init__` lo impone
(`context_budget.py · L54–88`): `warning_ratio <= compaction_ratio <= hard_ratio`, ogni
rapporto in `(0, 1]`, e una riserva di output che lasci davvero spazio.

Senza quel controllo una configurazione invertita non fallisce: `decide` salta la zona di
allerta e l'harness smette di offloadare prima di comprimere, senza che nessun errore lo
dica. È il tipo di difetto che non si manifesta come crash ma come comportamento
leggermente peggiore, cioè il più difficile da attribuire.

---

## Offload: recupero grande a informazione zero persa

L'output lungo di un tool esce dal contesto ma **non sparisce**: resta su file nel
workspace, e nel prompt entra un sostituto compatto.

**Evidenza:** `context_budget.py · L202–240`.

```
[offload] ref=/workspace/.tool_output/<sha>.txt sha256=<sha> (~12000 token). Estratto:
<primi 500 caratteri>…
```

Il checksum non è decorativo: *«lega il riferimento al contenuto esatto: se il file cambia,
il checksum non combacia più e il modello sa che l'estratto potrebbe non riflettere
l'originale»* (`context_budget.py · L227–228`).

Il middleware che lo applica preserva il protocollo tool: il `ToolMessage` e il suo
`tool_call_id` restano al loro posto, cambia solo il contenuto
(`context_budget.py · L319–321`). Alterare quella struttura romperebbe la corrispondenza
chiamata↔risposta che il provider si aspetta.

Stesso meccanismo usato dalla [sandbox](esecuzione-in-sandbox.md#output-lungo-offload-non-troncamento)
per gli output di `docker_exec`: `sandbox.py` importa `offload_tool_output` da qui.

---

## Drop dei duplicati: deterministico e senza perdita

`drop_reconstructible` rimuove gli output di tool duplicati consecutivi per lo stesso
`tool_call_id`, tenendo solo l'ultima osservazione (`context_budget.py · L242–259`).

Il docstring rivendica due proprietà: **deterministico** e **senza perdita** — un tool
idempotente riletto non aggiunge informazione. Scorre la lista al contrario proprio per
tenere l'ultima occorrenza.

---

## Riassunto strutturato, non prosa

`StructuredSummary` non è un blocco di testo libero: è uno schema con campi
(`context_budget.py · L262–302`).

| Campo | Cosa preserva |
|---|---|
| `goal` | l'obiettivo |
| `constraints` | i vincoli |
| `decisions` | le decisioni prese |
| `completed` / `open_items` | cosa è fatto e cosa resta |
| `artifacts` | path + checksum dei file prodotti |
| `verification` | prove raccolte |
| `failures` | errori ancora aperti |

Il docstring dichiara l'invariante: *«Obiettivo, vincoli, decisioni, errori aperti e prove
non si buttano mai; le chiacchiere intermedie sì»* (`context_budget.py · L266–267`).

Lo schema è lo stesso del piano, così la UI può renderizzarlo e il modello può ricostruire
lo stato senza rileggere l'intera storia. Un riassunto in prosa libera non darebbe nessuna
delle due cose.

---

## Riepilogo evidenza

| Sito | Righe | Ruolo |
|---|---|---|
| `src/agent_harness/context_budget.py` | L28–37 | scala delle azioni |
| `src/agent_harness/context_budget.py` | L39–88 | soglie, validazione, finestra utile |
| `src/agent_harness/context_budget.py` | L110–144 | ispezione e snapshot |
| `src/agent_harness/context_budget.py` | L146–177 | politica di decisione |
| `src/agent_harness/context_budget.py` | L202–240 | offload con checksum |
| `src/agent_harness/context_budget.py` | L242–259 | drop dei duplicati |
| `src/agent_harness/context_budget.py` | L262–302 | riassunto strutturato |
| `src/agent_harness/context_budget.py` | L305–313 | budget dalla configurazione |
| `src/agent_harness/context_budget.py` | L316–381 | middleware di offload |
| `src/agent_harness/context_budget.py` | L383–396 | throttle dell'usage live |
| `src/agent_harness/context_monitor.py` | — | monitoraggio lato control plane |

**Test:** `tests/test_context_budget.py`, `tests/test_context_monitor.py`.

---

## Note per chi modifica

- **Non mettere esecuzione dentro `decide`.** La separazione è ciò che rende la politica
  testabile offline; è anche ciò che permette di emettere l'azione come evento prima di
  applicarla.
- **Non toccare `tool_call_id` durante l'offload.** Il protocollo tool del provider si
  romperebbe in modo difficile da diagnosticare.
- **Aggiungere un campo a `StructuredSummary`** → va allineato con lo schema del piano,
  altrimenti la UI smette di renderizzarlo.
- **Non rimuovere `__post_init__`.** Fino a poco fa non c'era, e una configurazione con
  `warning_ratio` sopra `compaction_ratio` non falliva: produceva silenziosamente una zona
  di allerta inesistente. Un budget mal configurato va rifiutato quando lo si costruisce,
  non dedotto dal comportamento.
