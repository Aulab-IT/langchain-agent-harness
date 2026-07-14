# Delivery policy

Questa policy definisce il confine tra un run che produce artefatti e una delivery reale.

## Condizioni obbligatorie

Merge, deploy e migrazioni sono autorizzabili solo quando il dossier del run dimostra:

1. manifest e artefatti integri;
2. checker indipendente superato su snapshot read-only;
3. branch diverso da `main`/`master` e worktree pulito;
4. pipeline CI conclusa con successo;
5. ambiente preview disponibile;
6. piano di rollback registrato;
7. decisione umana esplicita legata all'hash del manifest.

Un'approvazione umana non annulla gli altri controlli. Se l'artefatto o il manifest cambiano,
la decisione non è più valida per il nuovo hash.

## Rollback

Per cambiamenti Git si usa un commit di revert del commit approvato. Per deploy o migrazioni il
run deve indicare la versione precedente e la procedura di ripristino prima dell'approvazione.
Il rollback non deve cancellare la cronologia del branch né riscrivere gli eventi del dossier.

## Limite attuale

Il Control Center registra e valuta il gate, ma non esegue merge o deploy. L'integrazione futura
deve interrogare il gate e rifiutare l'operazione quando `delivery.ready` è `false`.
