# L3 · Confinamento del filesystem

**Unità:** stadio 1 · configurazione e composizione → [1.1](../L2_UNITA.md#11--confinamento-del-filesystem)

*Ogni lettura e scrittura dell'agente resta dentro la radice della sessione,
indipendentemente dal path che il modello chiede. Non è un gate che chiede permesso: è un
confine che nega.*

Differenza con l'[approvazione](approvazione-azioni-sensibili.md), che vale la pena tenere
ferma: 4.1 sospende e domanda; qui non si domanda niente. Un path fuori confine è
semplicemente negato.

---

## Le tre difese sovrapposte

Il confinamento non sta in un solo posto. Tre meccanismi indipendenti, ognuno sufficiente a
fermare un caso che gli altri lascerebbero passare.

### 1 · Radice virtuale del backend

```python
backend = FilesystemBackend(root_dir=active_backend_root, virtual_mode=True)
```

**Evidenza:** `factory.py · L775`.

`virtual_mode=True` significa che i path che il modello vede (`/workspace/dati.csv`) non
sono path del sistema ospite: vengono risolti sotto `active_backend_root`. Il modello non
ha nemmeno il vocabolario per nominare un file fuori dalla radice — `/etc/passwd` per lui è
un path dentro la radice virtuale.

### 2 · Lista di permessi con deny finale

**Evidenza:** `factory.py · L111–135` (`build_workspace_permissions`).

| Operazioni | Path | Modo |
|---|---|---|
| read, write | `/workspace`, `/workspace/**`, `/memories`, `/memories/**` | allow |
| read | `/skills`, `/skills/**` | allow |
| **write** | `/skills`, `/skills/**` | **deny** |
| read, write | `/**` | **deny** |

Da leggere dal basso: l'ultima regola nega tutto, le precedenti aprono eccezioni mirate. È
una allow-list, non una deny-list — aggiungere un path nuovo al filesystem non lo rende
accessibile per sbaglio.

La riga che conta di più è la terza: le skill sono **leggibili ma non scrivibili**.
L'agente può eseguire una skill, non può riscriversela. Impedisce il caso in cui un agente
modifica le proprie istruzioni per aggirare un vincolo — la modifica delle skill passa
dalla UI, non dal filesystem del run.

I mount sono costanti condivise, non stringhe ripetute: `SANDBOX_WORKSPACE_MOUNT` e
`SANDBOX_SKILLS_MOUNT` in `config.py · L19–20`. Sono gli stessi valori usati dai mount
Docker in [4.3](esecuzione-in-sandbox.md), quindi ciò che l'agente vede nel filesystem e ciò
che vede nella sandbox coincide per costruzione.

### 3 · Isolamento per sessione

Ogni conversazione ha la sua radice: `state/sessions/<thread_id>/workspace`.

**Evidenza:** `control_store.py · L1082–1083` (`workspace_dir`),
`control_store.py · L1088–1092` (`prepare_session_root`).

Due thread non condividono niente: né allegati, né artefatti, né memorie. Un agente non può
leggere il lavoro di un'altra conversazione perché quella conversazione è fuori dalla sua
radice — di nuovo per costruzione, non per controllo.

`prepare_session_root` ricopia le skill da zero a ogni run, così modifiche ed eliminazioni
fatte dal pannello si riflettono nel run successivo (`control_store.py · L1093–1094`).

---

## Least privilege per i subagenti

I subagenti non ereditano i permessi del padre: ne ricevono uno più stretto.

**Evidenza:** `factory.py · L138–152` (`_read_only_permissions`), applicato a
`factory.py · L186` e `factory.py · L220`.

| Operazioni | Path | Modo |
|---|---|---|
| read | `/workspace`, `/workspace/**`, `/memories`, `/memories/**` | allow |
| write | `/**` | deny |
| read | `/**` | deny |

Un subagente di ricerca o revisione **legge e basta**. Non c'è un path in cui possa
scrivere: la deny su `write /**` non ha nessuna eccezione sopra di sé. Il risultato del
subagente torna al padre come testo, e sarà il padre — che i permessi di scrittura ce li ha
— a decidere se materializzarlo.

---

## Cosa questo confine **non** copre

Utile quanto sapere cosa copre:

- **Non copre i comandi in sandbox.** `docker_exec` non passa dal `FilesystemBackend`: ha il
  suo confine, i mount Docker di [4.3](esecuzione-in-sandbox.md). Sono due meccanismi
  paralleli allineati sulle stesse costanti, non uno che contiene l'altro.
- **Non copre le richieste di rete.** Confine separato, `browser.py` con difese SSRF.
- **Non è un gate.** Non produce eventi, non chiede conferma, non compare nella trace. Se
  stai cercando perché un'operazione su file è stata bloccata, non la trovi tra gli
  `approval.*`: la trovi come errore di permesso restituito al modello.

---

## Riepilogo evidenza

| Sito | Righe | Ruolo |
|---|---|---|
| `src/agent_harness/config.py` | L19–20 | costanti dei mount, condivise con la sandbox |
| `src/agent_harness/factory.py` | L111–135 | allow-list dell'agente principale |
| `src/agent_harness/factory.py` | L138–152 | permessi read-only dei subagenti |
| `src/agent_harness/factory.py` | L186, L220 | applicazione ai subagenti |
| `src/agent_harness/factory.py` | L775–776 | backend virtuale e permessi nel grafo |
| `src/agent_harness/control_store.py` | L1082–1094 | radice per sessione, skill ricopiate |

**Test:** `tests/test_factory.py`, `tests/test_control_store.py`.

---

## Note per chi modifica

- **Aggiungere un path scrivibile** → `factory.py · L111–135`, sopra la deny finale. Se lo
  metti sotto non ha effetto e nessun test te lo dice.
- **Non togliere la deny su `/skills`.** È ciò che impedisce a un run di riscriversi le
  proprie istruzioni.
- **Non allentare `_read_only_permissions`.** Se un subagente deve produrre un artefatto, la
  strada è restituirlo al padre, non dargli la scrittura.
- Cambiare `SANDBOX_WORKSPACE_MOUNT` tocca *anche* i mount Docker: le due unità condividono
  la costante apposta.
