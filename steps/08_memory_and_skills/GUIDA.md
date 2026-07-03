# Step 08 — Memoria continua e skills

## Obiettivo

Facciamo apprendere all'agente informazioni che superano il singolo thread, evitando di
caricare sempre tutte le procedure disponibili.

## Memoria e skill non sono sinonimi

`AGENTS.md` è memoria sempre rilevante. Viene iniettata nel prompt all'avvio e può
contenere convenzioni, preferenze e apprendimenti durevoli.

Una skill è una procedura specifica. All'inizio il modello vede soltanto nome e
descrizione; legge il corpo completo di `SKILL.md` quando il compito la rende pertinente.
Questa progressive disclosure protegge la finestra di contesto.

## Procedura manuale

1. Crea `memories/AGENTS.md`.
2. Crea `skills/nome-skill/SKILL.md`.
3. Inserisci nel frontmatter della skill `name` e `description`.
4. Punta `FilesystemBackend` alla radice che contiene entrambe le directory.
5. Passa a `create_deep_agent`:

   ```python
   memory=["/memories/AGENTS.md"]
   skills=["/skills/"]
   ```

## Prova

```bash
uv run python -m steps.08_memory_and_skills.app
```

Poi assegna un compito di ricerca e osserva nelle tracce quando viene letto il relativo
`SKILL.md`.

## Cosa non memorizzare

Chiavi API, password, token, dati personali non necessari e contenuti ricevuti da fonti
non attendibili. La memoria è persistente: un errore qui si propaga ai thread futuri.

## Esercizio

Crea una skill per revisionare documentazione Markdown. La descrizione deve permettere al
modello di distinguerla dalla skill di ricerca.

