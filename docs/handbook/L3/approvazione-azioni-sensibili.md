# L3 · Approvazione di azioni sensibili (HITL)

**Unità:** stadio 4 · esecuzione guardata degli effetti collaterali → [4.1](../L2_UNITA.md#41--approvazione-di-azioni-sensibili-hitl--unità-pilota)

Il comportamento in una frase: *quando il modello chiede di eseguire un comando in sandbox
o di aggiungere un server MCP, l'harness decide se la cosa può passare da sola; se non può,
sospende il run, mostra all'utente una descrizione ricostruita dell'azione, e riprende solo
con la sua decisione.*

Sette siti di implementazione, due linguaggi.

---

## Trigger

Il modello emette una tool call. Il `HumanInTheLoopMiddleware` di Deep Agents la confronta
con la mappa `interrupt_on` composta al momento della costruzione del grafo.

**Evidenza:** `factory.py · L781–798` (definizione), `factory.py · L1043` (passaggio a `create_deep_agent`).

Due tool sono nella mappa. Nient'altro apre mai un'approvazione:

| Tool | Decisioni ammesse | Condizione (`when`) |
|---|---|---|
| `docker_exec` | `approve`, `reject` | `docker_exec_requires_approval(...)` |
| `propose_mcp_server` | `approve`, `reject` | `lambda req: True` — costante |

---

## Regola di permesso

```python
def docker_exec_requires_approval(args, *, require_approval, auto_approve) -> bool:
    """Rete sempre gated; autonomia salta solo approval locali configurate."""
    return bool(args.get("with_network")) or (require_approval and not auto_approve)
```

**Evidenza:** `factory.py · L85–90`.

Da leggere come una disgiunzione con una gamba non negoziabile:

- `with_network=true` → **sempre** approvazione. Nessuna configurazione la disattiva.
- Altrimenti → approvazione se la configurazione la richiede
  (`harness_require_approval`, default `True` in `config.py · L144`) e la sessione non è in
  autonomia.

`propose_mcp_server` ha `when` costante-`True` con un commento che spiega il perché: un
server MCP stdio gira **sull'host, fuori dalla sandbox Docker**, quindi cambia i privilegi
del sistema, non solo quelli del container. Il costante-`True` è deliberato — impedisce che
un futuro refactor della condizione lasci passare questa azione insieme alle altre
(`factory.py · L790–797`).

---

## Percorso di esecuzione

### Il loop di sospensione

Il grafo si ferma e restituisce uno stato con la chiave `__interrupt__`. `GoalRunner` lo
gestisce in un `while`, perché un singolo run può sospendersi più volte.

**Evidenza:** `runner.py · L157–198`.

```
_invoke_graph(value)
  └─ "__interrupt__" in result ?
       ├─ payload["type"] == "user_action"  → unità 4.2, ramo separato   (L169–174)
       ├─ approval_callback is None         → RuntimeError               (L175–176)
       └─ approved = await approval_callback(payload)                    (L177)
              ↓
          decision = approve | reject                                    (L178–185)
              ↓
          Command(resume={"decisions": [decision] * N})                  (L194–197)
              ↓
          torna in cima al while
```

Il rifiuto non è un'eccezione: è una decisione `{"type": "reject", "message": ...}` che
torna al modello come osservazione. L'agente prosegue sapendo di essere stato bloccato.

### Il fan-out delle decisioni — il dettaglio non ovvio

`HumanInTheLoopMiddleware` sospende con **un** interrupt per turno, ma i tool sensibili
chiamati in parallelo nello stesso turno finiscono tutti in `payload["action_requests"]`.
Il middleware pretende una decisione per ciascuno; con una sola, `after_model` solleva
`"Number of human decisions does not match number of hanging tool calls"` e il run fallisce.

La soluzione: la UI resta a **una conferma per turno**, e il runner replica quella decisione
su tutte le tool call pendenti.

**Evidenza:** `runner.py · L186–197`.

> **Conseguenza da conoscere prima di modificare qui.** L'utente approva o rifiuta *in
> blocco*. Non può approvare la prima delle tre `docker_exec` di un turno e rifiutare le
> altre due. Se in futuro serve una granularità per-call, il cambiamento è nella UI e nel
> conteggio, non nel middleware.

---

## Cambi di stato

| Momento | Cosa cambia | Evidenza |
|---|---|---|
| Sospensione | run → `waiting_approval` | `server.py · L1203` |
| Sospensione | interrupt persistito in SQLite | `server.py · L1204`, `durable.py · L528–564` |
| Sospensione | notifica push all'utente | `server.py · L1205–1210` |
| Sospensione | evento `approval.requested` sul flusso SSE | `server.py · L1211` |
| Risoluzione | `Future` completata dal REST | `server.py · L1693–1698` |
| Risoluzione | interrupt marcato risolto, idempotente | `server.py · L1218`, `durable.py · L566–608` |
| Risoluzione | evento `approval.resolved` | `server.py · L1223` |
| Auto-approvazione | evento `approval.auto`, nessuna sospensione | `server.py · L1199` |

Lo stato `WAITING_APPROVAL` è parte della state machine dichiarata in `durable.py · L42`, non
una stringa ad hoc.

---

## Ricostruzione del payload (non è cosmesi)

L'utente **non vede mai il payload grezzo dell'interrupt**. Ne viene costruito uno nuovo,
con solo i campi che servono a decidere.

**Evidenza:** `command_review.py · L193–225` (`build_approval_summary`).

```python
summary = {
    "action": action,
    "description": "Accesso rete temporaneo alla sandbox Docker (per questo comando)"
                   if is_network else
                   "Esecuzione comando in sandbox Docker isolata",
}
if is_network:
    summary["network"] = True
command = extract_command(payload)
if command:
    summary["command"] = command
    summary["review"] = review_command(command).as_dict()
```

La funzione vive in `command_review.py` e non nel control plane per una ragione precisa,
scritta nel suo docstring: **ogni superficie di approvazione deve mostrare le stesse
informazioni**. Finché questa logica è stata solo lato web, chi approvava da terminale
decideva senza la classificazione del comando — la stessa decisione di sicurezza presa con
meno elementi. Il control plane la invoca a `server.py · L1192`, la CLI a `cli.py · L64`.

`review_command` (`command_review.py · L227`) classifica staticamente il comando: programmi
invocati, categorie, path toccati, warning. Il commento è preciso sul suo statuto: *«Non è
un'autorizzazione, è una spiegazione»* (`command_review.py · L221–222`). Serve a rendere la
decisione informata, non a prenderla.

Per `propose_mcp_server` la ricostruzione è diversa e mostra nome e config del server, con
la descrizione che dice esplicitamente «Gira sull'host, FUORI dalla sandbox Docker»
(`server.py · L1152–1164`).

---

## Casi limite

### Modalità autonoma

Letta **live a ogni richiesta**, non catturata all'inizio del run: cambiare la modalità
mentre il run gira ha effetto immediato sulla richiesta successiva.

**Evidenza:** `server.py · L1194–1199`.

L'eccezione è nel codice e nel commento: `if not is_network and ...auto_approve`. La rete
resta gated anche in autonomia. Stessa invariante espressa due volte, nella policy
(`factory.py · L89`) e qui — ridondanza deliberata su un confine di sicurezza.

### Timeout

L'attesa dell'approvazione ha un limite di **600 secondi** (`server.py · L1213`). Alla
scadenza la future viene rimossa e il run non resta appeso per sempre.

### Riavvio del processo

Gli interrupt pendenti sopravvivono, perché stanno in SQLite e non solo nel dizionario
`self.approvals` in memoria. `GET /api/durable/interrupts` li elenca dopo il riavvio —
esiste come prova osservabile della proprietà, non solo come endpoint di comodo
(`server.py · L2011–2024`, `durable.py · L610–617`).

Le `Future` in memoria invece **non** sopravvivono: dopo un riavvio l'interrupt risulta
pendente ma non c'è più nessuno in attesa di quella risposta specifica. Il run va ripreso,
non semplicemente approvato.

### Annullamento durante l'attesa

`cancel` completa la future pendente con `False` — un annullamento vale come rifiuto, non
lascia il grafo bloccato (`server.py · L1708–1712`).

### Fine del run con interrupt orfani

`_close_pending_interrupts` risolve tutto ciò che è rimasto pendente con
`{"cancelled": True}` e `resolved_by="system"`, così un run terminato non lascia righe
`pending` in SQLite (`server.py · L1676–1691`).

### Nessun callback

Se il grafo si sospende ma non è stato fornito un `approval_callback`, il runner solleva
`RuntimeError("Esecuzione sospesa: manca un callback di approvazione.")` invece di
proseguire (`runner.py · L175–176`). È il fallback corretto: un harness senza superficie di
approvazione non deve poter eseguire azioni sensibili.

---

## Le due superfici

| | CLI | Control Center |
|---|---|---|
| Callback | `ask_approval` (`cli.py · L63–76`) | `approval` (`server.py · L1150`) |
| Riepilogo mostrato | `build_approval_summary` | `build_approval_summary` |
| Presentazione | Panel Rich (`cli.py · L36–60`) | modale React con badge di rischio |
| Rete | prompt dedicato, `default=False` (`cli.py · L70–75`) | badge `network` + descrizione dedicata |
| Auto-approvazione | non disponibile | per sessione, `PATCH /api/sessions/{id}/auto-approve` |
| Risposta | `typer.confirm` | `POST /api/runs/{id}/approve` \| `/reject` (`server.py · L2539–2549`) |

**Le due superfici mostrano le stesse informazioni.** Comando, descrizione, categorie, path
toccati e avvisi passano da `build_approval_summary` in entrambi i casi; cambia solo il
rendering — `render_approval` per il terminale (`cli.py · L36–60`), `ApprovalDialog` per il
browser.

> Non è sempre stato così. La CLI stampava il payload grezzo in JSON e non mostrava la
> classificazione statica del comando: chi approvava da terminale prendeva la stessa
> decisione di sicurezza con meno elementi di chi approvava dal browser. L'asimmetria è
> emersa scrivendo questa pagina — nessun test la copriva, perché nessuno dei due percorsi
> era sbagliato preso da solo. Oggi `tests/test_cli.py` verifica la parità.

Sul client, il modale è montato in `App.tsx · L231–239` e implementato in
`ApprovalDialog.tsx · L107–258`, che rende labels, path e warning prodotti da
`review_command` (`ApprovalDialog.tsx · L134–137`).

---

## Riepilogo evidenza

| Sito | Righe | Ruolo |
|---|---|---|
| `src/agent_harness/factory.py` | L85–90 | regola di permesso per `docker_exec` |
| `src/agent_harness/factory.py` | L781–798 | mappa `interrupt_on` |
| `src/agent_harness/factory.py` | L1043 | iniezione nel grafo |
| `src/agent_harness/runner.py` | L157–198 | loop di sospensione, decisione, fan-out |
| `src/agent_harness/server.py` | L1150–1188 | ramo `propose_mcp_server` |
| `src/agent_harness/server.py` | L1192–1224 | ricostruzione payload, autonomia, attesa |
| `src/agent_harness/server.py` | L1676–1691 | chiusura interrupt orfani |
| `src/agent_harness/server.py` | L1693–1698 | risoluzione dal REST |
| `src/agent_harness/server.py` | L2539–2549 | endpoint approve/reject |
| `src/agent_harness/durable.py` | L42, L207–224, L528–608 | stato, schema, persistenza idempotente |
| `src/agent_harness/command_review.py` | L164–191 | rete richiesta ed estrazione del comando |
| `src/agent_harness/command_review.py` | L193–225 | riepilogo mostrato, comune alle superfici |
| `src/agent_harness/command_review.py` | L227–260 | classificazione statica del comando |
| `src/agent_harness/cli.py` | L36–76 | superficie di approvazione da terminale |
| `client/src/App.tsx` | L231–239 | montaggio del modale |
| `client/src/components/shared/ApprovalDialog.tsx` | L107–258 | raccolta della decisione |

**Test che coprono l'unità:** `tests/test_runner.py`, `tests/test_factory.py`,
`tests/test_server.py`, `tests/test_durable.py`, `tests/test_command_review.py`.

---

## Note per chi modifica

Il confine della modifica, se devi toccare questo comportamento:

- **Aggiungere un tool da gattare** → `factory.py · L781–798`, e valuta se serve una
  ricostruzione dedicata del payload in `server.py` come per `propose_mcp_server`.
- **Cambiare quando si può auto-approvare** → due siti da tenere allineati,
  `factory.py · L85–90` e `server.py · L1194–1199`. Toccarne uno solo rompe l'invariante
  senza far fallire nessun test in modo ovvio.
- **Granularità per-tool-call** → `runner.py · L192–196` più la UI. Non il middleware.
- **Nuova superficie di approvazione** → un callback con la firma
  `async (payload: dict) -> bool` passato al `GoalRunner`, che rende
  `build_approval_summary(payload)`. Non serve toccare il grafo — ma **non costruire un
  riepilogo proprio**: è così che è nata l'asimmetria fra CLI e web.
- **Cambiare cosa si mostra prima di approvare** → `command_review.py · L193–225`, un solo
  sito per entrambe le superfici.

Invarianti da non rompere: la rete resta sempre gated; l'aggiunta di server MCP resta sempre
gated; il numero di decisioni resta uguale al numero di tool call pendenti; un run terminato
non lascia interrupt pendenti; ogni superficie mostra lo stesso riepilogo.
