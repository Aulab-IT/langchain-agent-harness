# Step 01 — Dal modello al loop conversazionale

## Obiettivo

Creiamo il primo involucro attorno al modello: un prompt di sistema e una cronologia di
messaggi.

## Perché è già un harness

Un modello riceve input e produce output. Non conserva autonomamente la conversazione.
La lista `messages` e il ciclo `while` sono responsabilità del programma:

1. ricevere il testo dell'utente;
2. aggiungerlo alla cronologia;
3. chiamare il modello;
4. conservare anche la risposta;
5. ripetere.

## Procedura manuale

1. Parti dallo step 00.
2. Importa `ChatOpenAI` e i tipi di messaggio.
3. Crea il modello con `store=False`: la persistenza sarà gestita dal nostro harness.
4. Inserisci un `SystemMessage` come primo elemento.
5. Implementa il ciclo mostrato in `app.py`.
6. Avvia:

   ```bash
   uv run python -m steps.01_model_loop.app
   ```

7. Scrivi prima «Mi chiamo Ada» e poi «Come mi chiamo?».

## Cosa osservare

Il secondo turno funziona perché inviamo nuovamente l'intera lista. Se cancelli
`messages.append(response)`, il modello non vedrà più le proprie risposte precedenti.

## Limite

La lista cresce senza controllo e vive soltanto nel processo. Gli step successivi
aggiungeranno tool, checkpoint e compaction.

## Esercizio

Stampa il numero di messaggi prima di ogni chiamata e prova a riavviare il programma.
Spiega perché la conversazione viene persa.

