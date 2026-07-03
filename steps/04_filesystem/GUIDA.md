# Step 04 — Filesystem come memoria operativa

## Obiettivo

Diamo all'agente uno spazio in cui leggere dati, produrre artefatti e scaricare dal
contesto risultati intermedi.

## Perché il filesystem è fondamentale

Una finestra di contesto è costosa e temporanea. Un file:

- sopravvive a una singola chiamata;
- può contenere output molto grandi;
- è ispezionabile da studente, test e altri agenti;
- rappresenta lo stato del lavoro senza doverlo ripetere nel prompt.

## Procedura manuale

1. Installa `deepagents`.
2. Crea una directory `workspace`.
3. Risolvi il percorso assoluto.
4. Costruisci `FilesystemBackend` con quella directory come radice.
5. Usa `virtual_mode=True`: il modello vede percorsi virtuali come `/plan.md`.
6. Passa il backend a `create_deep_agent`.

Deep Agents aggiunge `ls`, `read_file`, `write_file`, `edit_file`, `glob` e `grep`.

## Prova

```bash
mkdir -p workspace
uv run python -m steps.04_filesystem.app
ls -la workspace
```

## Confine di sicurezza

La radice deve essere una directory dedicata, non la home dell'utente. Il filesystem
limita la superficie esposta ma non rende sicura l'esecuzione di comandi shell.

## Esercizio

Chiedi all'agente di produrre un file di 200 righe e poi di sintetizzarlo senza includere
tutto il contenuto nella risposta.

