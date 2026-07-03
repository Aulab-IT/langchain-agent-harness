# Step 07 — Gestire il deterioramento del contesto

## Obiettivo

Impediamo che una conversazione lunga o un singolo output enorme saturino la finestra di
contesto.

## Problema 1: cronologia lunga

Più messaggi non significano sempre più qualità. Informazioni obsolete e dettagli
intermedi competono con l'obiettivo corrente. `SummarizationMiddleware`:

1. osserva la dimensione della cronologia;
2. al raggiungimento del trigger invoca un modello di sintesi;
3. conserva gli ultimi messaggi;
4. sostituisce la parte più vecchia con un riepilogo operativo.

Nel progetto finale Deep Agents installa già questo middleware.

## Problema 2: output di tool enorme

Un log da centomila righe non deve essere copiato integralmente nei messaggi.
`FilesystemMiddleware` salva l'output completo su file e lascia nel contesto un riferimento
insieme alle parti utili. Il modello può leggere il file in seguito.

## Procedura manuale

1. Configura un backend filesystem.
2. Aggiungi `FilesystemMiddleware` con una soglia piccola per l'esperimento.
3. Aggiungi `SummarizationMiddleware`.
4. Scegli `trigger` e `keep` separatamente.
5. Usa lo stesso modello oppure un modello più economico per la sintesi.

## Prova

```bash
uv run python -m steps.07_context_management.app
```

Per vedere davvero la compaction, trasforma l'esempio in una chat e supera dodici
messaggi. In produzione è preferibile una soglia basata sui token.

## Compromesso

Una sintesi perde dettagli. File, piano e checkpoint permettono di conservare prove e
artefatti fuori dal riassunto.

