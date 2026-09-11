# L3 · Esecuzione in sandbox

**Unità:** stadio 4 · esecuzione guardata → [4.3](../L2_UNITA.md#43--esecuzione-in-sandbox)

*Il comando approvato viene eseguito in un container Docker dedicato alla conversazione,
con filesystem read-only tranne `/workspace`, senza capability, senza rete salvo
concessione esplicita per singolo comando, con limiti fermi di memoria, CPU e processi.*

È il *dopo* dell'[approvazione](approvazione-azioni-sensibili.md): qui arriva solo ciò che
ha superato il gate.

---

## Trigger

Il tool `docker_exec`, con schema `DockerExecInput` (`sandbox.py · L22–45`).

| Campo | Vincolo |
|---|---|
| `command` | stringa shell |
| `timeout_seconds` | 1–120, default 60 |
| `with_network` | default `False` |

Il vincolo su `timeout_seconds` è nel tipo, non in un controllo a runtime: il modello non
può chiedere un comando che gira per un'ora.

---

## Il confine di esecuzione

`run_flags` costruisce le opzioni di `docker run`. Ogni flag è un confine, e vale la pena
leggerli come un elenco di cose che il codice eseguito **non può** fare.

**Evidenza:** `sandbox.py · L296–359`.

| Flag | Confine |
|---|---|
| `--network <rete-interna-sessione>` | nessun accesso a internet |
| `--read-only` | filesystem del container immutabile |
| `--cap-drop ALL` | nessuna capability Linux |
| `--security-opt no-new-privileges` | niente escalation via setuid |
| `--memory 2g`, `--cpus 2`, `--pids-limit 512` | limiti fermi di risorse |
| `--user <uid>:<gid>` | non gira come root |
| `--tmpfs /tmp:rw,noexec,nosuid,size=512m` | scratch volatile, non eseguibile |
| `--mount type=bind,src=<workspace>,dst=/workspace` | **unica** superficie scrivibile persistente |
| `--mount ...,dst=/skills,readonly` | skill eseguibili ma non modificabili dal container |

Due dettagli che non si deducono guardando i flag:

**Perché non `--network none`.** Sarebbe l'isolamento più ovvio, ma Docker vieta di
collegare a caldo un'altra rete a un container avviato in modalità `none`. Con `none` la
concessione temporanea di internet sarebbe impossibile senza ricreare il container. Si usa
quindi una rete `--internal` dedicata alla sessione: equivalente in isolamento (nessuna
uscita verso internet), ma collegabile a caldo (`sandbox.py · L309–314`,
`sandbox.py · L124`).

**Perché i limiti sono 2g e non 512m.** Erano più stretti e sono stati alzati per un motivo
concreto documentato nel codice: installare client cloud, lavorare su PDF/PPTX o dataframe
pandas sfondava i 512 MB di RAM e soprattutto i 64 MB di `/tmp` — pip usa `/tmp` per cache e
build, e il risultato era «No space left on device» (`sandbox.py · L332–335`). Restano
limiti fermi: alzati una volta con una ragione, non rimossi.

**Ordine degli argomenti.** `run_flags` restituisce le opzioni **senza** l'immagine, perché
in `docker run [OPTIONS] IMAGE [COMMAND]` tutto ciò che segue l'immagine è comando, non
opzione. Un flag messo dopo l'immagine non fallisce: viene silenziosamente eseguito come
comando. Il docstring lo dice esplicitamente (`sandbox.py · L303–308`).

---

## Concessione di rete per singolo comando

Quando `with_network=true` è stato approvato, la rete non viene «accesa per il run»: viene
collegata per **quel singolo exec** e revocata sempre.

**Evidenza:** `sandbox.py · L439–461`.

```python
if with_network:
    self._connect_network(container, network)
try:
    result = subprocess.run(["docker", "exec", container, "sh", "-lc", command], ...)
finally:
    if with_network:
        self._disconnect_network(container, network)
```

Il `finally` è la garanzia: la rete viene revocata anche se il comando fallisce, va in
timeout o solleva. Il `connect` è idempotente rispetto a una connessione residua lasciata da
un run crashato — l'errore è ignorato con `check=False` e il `finally` ripulisce comunque
(`sandbox.py · L442–446`).

> Questa è la seconda metà dell'invariante «rete sempre gated»: la prima metà (chiedere
> conferma) sta in [4.1](approvazione-azioni-sensibili.md#regola-di-permesso), qui c'è la
> parte che garantisce che la concessione non sopravviva al comando.

---

## Percorsi di eccezione

Tutti gli errori diventano una **stringa di ritorno**, non un'eccezione che uccide il run.
L'agente li legge come osservazione e può reagire.

**Evidenza:** `sandbox.py · L462–468`.

| Situazione | Cosa vede l'agente |
|---|---|
| Docker assente dal PATH | `ERRORE: Docker non è installato o non è nel PATH.` |
| Timeout | `ERRORE: comando interrotto dopo N secondi.` |
| Avvio container fallito | `ERRORE: <dettaglio da stderr>` |
| Byte NUL nel comando | `ValueError` — rifiutato prima di partire (`sandbox.py · L437`) |

**Niente `text=True`.** Deliberato: forzerebbe una decodifica UTF-8 stretta di stdout, e un
comando che stampa byte non-UTF8 (npx, git, `cat` di un binario) farebbe crashare l'intero
run con `UnicodeDecodeError`. Si catturano i byte e si decodifica con `errors="replace"`
(`sandbox.py · L449–452`, `sandbox.py · L477–488`).

---

## Output lungo: offload, non troncamento

Se l'output supera `output_limit` (default 12.000 caratteri) l'integrale viene scritto in
`/workspace/.tool_output/<checksum>.txt` e nel contesto entra solo un estratto più il
riferimento.

**Evidenza:** `sandbox.py · L491–522`.

Il ragionamento è scritto nel docstring: prima si troncava testa+coda e la parte centrale
era persa per sempre, mentre nel contesto restavano comunque ~`output_limit` caratteri a
ogni turno successivo. Con l'offload il modello sa che il dato esiste e come rileggerlo,
pagando pochi token (`sandbox.py · L492–501`).

Il checksum dipende solo dal contenuto: due esecuzioni con lo stesso output producono lo
stesso file. Se la scrittura fallisce si ricade sull'ex-troncamento — un problema di
filesystem non deve far perdere del tutto l'output (`sandbox.py · L519–522`).

La cartella è nascosta (`.tool_output`) per non comparire tra gli allegati della sessione.

---

## Ciclo di vita del container

Un container **per sessione**, persistente tra i comandi, non uno per exec.

| Operazione | Evidenza |
|---|---|
| Avvio pigro al primo uso | `sandbox.py · L362–409` (`ensure_running`) |
| Verifica post-avvio | `sandbox.py · L406–407` — se non risulta running, errore esplicito |
| Stop e rimozione rete di sessione | `sandbox.py · L411–422` |
| Lock per sessione | `sandbox.py · L76–78` — due exec concorrenti non avviano due container |

### Reaper di inattività

Un task in background ferma i container inattivi.

**Evidenza:** `sandbox.py · L559–619`.

Tre condizioni prima di fermare, tutte necessarie: il container è tra quelli in esecuzione,
la sessione **non è occupata**, e l'inattività supera la soglia (`sandbox.py · L589–598`).

Caso limite documentato: il timer riguarda solo l'uso avvenuto nel processo backend
corrente. Dopo un riavvio riparte da zero per i container già in esecuzione — deliberato,
per non spegnere di colpo un container che sta per essere riusato
(`sandbox.py · L559–566`).

Il loop cattura le eccezioni e continua: uno sweep fallito non uccide il reaper
(`sandbox.py · L601–607`).

### Disponibilità di Docker

`docker_available` ha un timeout generoso (20s) e memorizza brevemente l'esito positivo.
Motivo documentato: Docker Desktop raccoglie tutto lo stato di sistema, e con un timeout
stretto andava sporadicamente in timeout facendo credere all'agente che Docker non fosse
attivo quando lo era (`sandbox.py · L160–188`).

---

## Riepilogo evidenza

| Sito | Righe | Ruolo |
|---|---|---|
| `src/agent_harness/sandbox.py` | L22–45 | schema del tool |
| `src/agent_harness/sandbox.py` | L113–128 | rete `--internal` di sessione |
| `src/agent_harness/sandbox.py` | L160–188 | disponibilità Docker con cache breve |
| `src/agent_harness/sandbox.py` | L230–249 | connect/disconnect rete |
| `src/agent_harness/sandbox.py` | L296–359 | flag di confinamento |
| `src/agent_harness/sandbox.py` | L362–422 | avvio pigro, stop, pulizia rete |
| `src/agent_harness/sandbox.py` | L424–475 | esecuzione, concessione rete, eccezioni |
| `src/agent_harness/sandbox.py` | L491–522 | offload dell'output lungo |
| `src/agent_harness/sandbox.py` | L559–619 | reaper di inattività |
| `src/agent_harness/sandbox.py` | L671–684 | esposizione come tool |
| `docker/` | — | immagine dell'ambiente |

**Test:** `tests/test_sandbox.py`.

---

## Note per chi modifica

- **Non sostituire la rete di sessione con `--network none`.** Rompe la concessione
  temporanea di internet. Il motivo è a `sandbox.py · L309–314`.
- **Aggiungere flag a `run_flags`** → devono stare **prima** dell'immagine. Un flag dopo
  l'immagine diventa parte del comando, senza errore visibile.
- **Alzare i limiti** → si può, ma con una ragione scritta nel commento come è stato fatto
  per 2g. Rimuoverli no.
- Il `finally` che revoca la rete a `sandbox.py · L459–461` è un'invariante di sicurezza:
  qualunque refactor dell'esecuzione deve mantenerlo, anche se cambia il resto.
