# Step 09 — Pianificazione e auto-verifica

## Obiettivo

Aiutiamo l'agente a mantenere coerenza durante un lavoro lungo e gli chiediamo prove,
non una semplice dichiarazione di successo.

## Due livelli di piano

Deep Agents include `write_todos`, utile per lo stato strutturato del turno. Un file
`/plan.md` sopravvive invece a compaction, continuazioni e cambi di agente. Nel progetto
usiamo entrambi:

- todo per la prossima sequenza operativa;
- file per decisioni, avanzamento e lavoro residuo.

## Verifica come feedback

Il tool `docker_exec` permette un ciclo deterministico:

1. scrivere codice;
2. eseguire test;
3. osservare stdout, stderr ed exit code;
4. correggere;
5. ripetere.

Il modello non decide se il processo è uscito con codice zero: quel fatto arriva
dall'ambiente.

## Procedura manuale

1. Aggiungi il sandbox dello step 05 ai tool.
2. Specifica nel prompt quando pianificare.
3. Richiedi un file di piano per attività con più passaggi.
4. Richiedi una verifica prima della conclusione.
5. Conserva il comando e il risultato in `verification.md`.

## Prova

```bash
uv run python -m steps.09_planning_and_verification.app
```

## Limite

Un prompt può essere ignorato. Lo step 11 aggiungerà approvazioni, limiti e continuazione
nel codice dell'harness.

