# Step 13 — Loop engineering

## Obiettivo

Oltre all'anatomia dell'harness, l'articolo
[*The Art of Loop Engineering*](https://www.langchain.com/blog/the-art-of-loop-engineering)
descrive quattro loop impilati. Il Loop 1 (agente + tool) è già tutto l'harness costruito
negli step precedenti. Qui aggiungiamo i tre loop che lo circondano, in versione locale.

## Loop 2 — Verifica con rubric

Il gate deterministico dello step 09 dice se un comando è uscito con codice zero, ma non
se la risposta è davvero buona. Il modulo `verification.py` aggiunge un `RubricGrader`: un
giudice basato sul modello forte assegna un punteggio per criterio (completezza, prove di
verifica, aderenza, sicurezza) e restituisce un feedback. La soglia resta deterministica in
Python. Se la risposta non passa, il `GoalRunner` reinietta il feedback nel budget di
continuazione già esistente, invece di limitarsi a ripetere l'obiettivo.

## Loop 3 — Trigger a eventi

Finora ogni run parte da una richiesta esplicita. `triggers.py` aggiunge uno scheduler
asincrono che valuta espressioni cron (`cron_matches`) e un endpoint webhook protetto da
token: un evento avvia un run autonomo. Il payload dell'evento è trattato come dato non
attendibile, mai come istruzioni.

## Loop 4 — Hill climbing

`improve.py` seleziona gli ultimi run terminali e legge solo gli eventi correlati ai loro
`run_id`: esiti funzionali, score e feedback del grader, chiamate/errori/retry dei tool,
latenza e token. Gli eventi streaming non accorciano la finestra e l'audit storico non
mescola periodi diversi. Un agente d'analisi propone modifiche alla configurazione entro una
whitelist (`system_prompt_addendum`, `harness_max_tool_calls`). Rubric e soglia restano
congelate. La proposta viene confrontata con la baseline sull'eval set deterministico; solo
un gate passato permette canary o promotion versionata. Rollback ripristina una versione
precedente senza patch dirette al codice.

## Procedura manuale

Esegui `app.py` per vedere i tre loop in sequenza: una verifica a rubric, un match cron e una
proposta di miglioramento generata dai trace. Servono `OPENAI_API_KEY` e un modello forte
configurato. Il comando `harness improve` e la vista "Miglioramenti" del Control Center usano
la stessa pipeline.
