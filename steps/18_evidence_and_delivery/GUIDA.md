# Step 18 — Evidenze e confine di delivery

## Obiettivo

Sostituire “fidati della risposta” con un dossier verificabile. Il manifest collega input, output,
artefatti, comandi, verifier, stato terminale e provenienza attraverso hash canonici.

## Catena di prova

`build_evidence_manifest` calcola hash e contratto minimo del task. `verify_evidence_manifest`
ricontrolla manifest e file nel workspace. `create_evidence_bundle` copia gli artefatti in uno
snapshot separato e read-only. `run_independent_checker` opera su quella copia: non può aggiustare
silenziosamente il risultato che sta verificando.

Il gate delivery è separato dal successo del run. Merge, deploy o migrazioni richiedono inoltre
branch isolato, worktree pulito, CI verde, preview, rollback e approvazione umana legata all’hash
del manifest. Se l’artefatto cambia, l’approvazione non vale più.

## Esecuzione

```bash
uv run python steps/18_evidence_and_delivery/app.py
```

Modifica `report.txt` dopo la creazione del manifest e riesegui la verifica: l’integrità fallisce,
mentre lo snapshot già creato conserva la versione controllata. Cambia il goal in “deploy”: il gate
diventa rilevante e resta chiuso finché mancano condizioni operative e decisione umana.

## Regola

Approvazione umana non sostituisce prove tecniche; prove tecniche non autorizzano delivery.
