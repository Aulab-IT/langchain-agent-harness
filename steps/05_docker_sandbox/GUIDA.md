# Step 05 — Esecuzione in sandbox Docker

## Obiettivo

Consentiamo all'agente di eseguire codice e test senza offrirgli una shell diretta sulla
macchina host.

## Minaccia affrontata

Un comando generato dal modello è input non attendibile. `subprocess.run(..., shell=True)`
sull'host gli darebbe i permessi dell'utente, accesso ai file leggibili e ai segreti
d'ambiente. Il progetto finale non usa questa soluzione.

## Costruzione del comando Docker

Apri `src/agent_harness/sandbox.py` e ricostruisci `command_line` un'opzione alla volta:

- `--rm`: elimina il container al termine;
- `--network none`: blocca traffico in uscita e in entrata;
- `--read-only`: rende immutabile il filesystem del container;
- `--cap-drop ALL`: rimuove capability Linux;
- `no-new-privileges`: impedisce escalation tramite eseguibili;
- `--memory`, `--cpus`, `--pids-limit`: limita consumo di risorse;
- `--tmpfs /tmp`: fornisce uno spazio temporaneo limitato;
- `--mount ... dst=/workspace`: condivide soltanto il workspace.

Usiamo una lista di argomenti per invocare Docker. Il comando dell'agente viene
interpretato da `sh` soltanto *dentro* il container.

## Prova

```bash
docker pull python:3.12-slim
uv run python -m steps.05_docker_sandbox.app
cat workspace/proof.txt
```

Prova poi `curl https://example.com`: deve fallire perché la rete è disabilitata.

## Limiti

Docker riduce il rischio, ma non va trattato come confine perfetto contro avversari
determinati. Non montare mai socket Docker, directory personali o file `.env`.

## Esercizio

Riduci il timeout a cinque secondi ed esegui `sleep 10`. Verifica che il processo venga
interrotto.

