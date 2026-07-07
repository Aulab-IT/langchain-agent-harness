# Step 11 — Human-in-the-loop, limiti e continuazione

## Obiettivo

Spostiamo alcune regole dal prompt al codice: un comando sensibile richiede approvazione,
il numero di tool è limitato e un'uscita prematura può essere intercettata.

## Approvazione umana

`interrupt_on={"docker_exec": ...}` sospende LangGraph prima dell'esecuzione. Il
checkpointer conserva lo stato. L'interfaccia mostra nome e argomenti e riprende con una
decisione `approve` o `reject`.

La scelta predefinita deve essere il rifiuto. Non approvare comandi senza leggerli.

**Tool sensibili in parallelo**: se il modello chiama più tool sensibili nello stesso
turno (es. due `docker_exec` insieme), LangGraph crea un solo interrupt ma con un
`action_requests` per ciascuno. `Command(resume={"decisions": [...]})` deve contenere
tante decisioni quante sono le `action_requests`, altrimenti `HumanInTheLoopMiddleware`
solleva `ValueError` e il run va in crash. Con una sola conferma in UI per turno, la
soluzione è ripetere la stessa decisione una volta per ogni tool call in sospeso
(vedi `GoalRunner._invoke_with_approval` in `runner.py`).

## Limite delle azioni

`ToolCallLimitMiddleware` impedisce loop incontrollati e costi illimitati. Anche il
sandbox impone timeout e limiti di risorse. I limiti sono meccanismi dell'harness, quindi
non dipendono dalla volontà del modello.

## Continuazione in stile Ralph loop

`GoalRunner` cerca `[GOAL_COMPLETE]`. Se manca:

1. mantiene file e checkpoint;
2. reinietta obiettivo e numero di iterazione;
3. chiede di leggere il piano e proseguire;
4. si ferma comunque al budget configurato.

Questo affronta l'arresto precoce senza creare un ciclo infinito.

## Procedura manuale

1. Configura un checkpointer.
2. Aggiungi `interrupt_on` al tool sensibile.
3. Gestisci `__interrupt__` e riprendi con `Command(resume=...)`.
4. Aggiungi `ToolCallLimitMiddleware`.
5. Incapsula le invocazioni in un ciclo con condizione e budget.
6. Conserva sempre lo stesso `thread_id` nelle riprese.

## Prova

```bash
uv run python -m steps.11_hitl_and_continuation.app
```

Rifiuta il primo comando e osserva come l'agente riceve la decisione. Ripeti approvando
un comando innocuo.

