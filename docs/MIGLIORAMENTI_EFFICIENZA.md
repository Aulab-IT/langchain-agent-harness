# Efficienza ed efficacia — miglioramenti ad alto impatto

**Data:** 12 luglio 2026
**Metodo:** misure reali sul codice attuale (branch `feat/pre-demo-harness`), non stime.
**Criterio:** ordinati per «risultato evidente» — ciò che si vede o si misura subito.

---

## Sintesi delle misure

| Cosa | Misura reale | Frequenza |
|---|---|---|
| Load MCP a inizio run (spawn stdio + list) | **3,71 s** | **ogni messaggio** |
| Ogni chiamata a un tool MCP (skill_*, count_text…) | **~1,0 s** | **ogni tool-call** |
| Schemi dei tool locali iniettati nel prompt | ~919 token | ogni chiamata al modello |
| System prompt | ~928 token | ogni chiamata al modello |
| Eval set | 20 casi | — |
| Continuazioni max per obiettivo | 3 | — |

Il dato che domina tutto: **`build_harness` viene ricostruito a ogni messaggio**
(`server.py:805`), e dentro c'è lo spawn del server MCP stdio. Sono **3,7 secondi di
tempo morto prima che il modello dica una parola**, pagati a ogni turno. Più ~1 s per ogni
skill usata. Su un compito che usa 3 skill: ~7 s buttati in overhead di processo.

---

## A. Efficienza — vincite di latenza/costo evidenti

### A1. Cache dell'harness per sessione (il più grosso) — risparmio ~3,7 s/messaggio

**Problema.** Ogni messaggio ricostruisce da zero: i 3 modelli, la connessione checkpointer
SQLite (`setup()`), il `MultiServerMCPClient` (che **spawna il subprocess** `python -m
agent_harness.mcp_server` e ne lista i tool), i subagenti, il grader. Il costo dominante è
l'MCP: **3,71 s misurati**, ogni turno.

**Fix.** Tenere un `Harness` vivo per `thread_id` (cache di processo), ricostruito solo se la
config cambia (fingerprint già esistente in `config_fingerprint`). Il checkpointer già persiste
lo stato fra i turni; l'oggetto graph può restare in memoria. Chiusura pigra a fine sessione o
con LRU + idle-reaper (già c'è il pattern per la sandbox).

**Risultato evidente.** Il secondo messaggio in poi risponde ~3,7 s prima. In demo si *vede*.

### A2. Overhead MCP per tool-call (~1 s ognuno) — server interno in-process

**Problema.** `langchain_mcp_adapters` con transport stdio **apre una sessione nuova (nuovo
subprocess) a ogni tool-call** — misurato ~1 s per chiamata, che è quasi tutto import di
`agent_harness` nel processo figlio. Un `skill_list` o un `count_text` costano 1 s di puro
fork+import.

**Fix.** Il server interno `local_harness` è didattico: i suoi tool (`count_text`,
`harness_glossary`, `skill_*`) sono funzioni Python locali. Registrarli **in-process** come
tool locali elimina tutto l'overhead MCP per il built-in. I server MCP **esterni**
(aggiunti dall'utente/agente) restano fuori processo — lì l'isolamento serve. In alternativa,
mantenere una sessione MCP persistente invece di ri-spawnare per chiamata.

**Risultato evidente.** Le skill diventano istantanee; il trace non mostra più 1 s morto per
ogni `skill_*`.

### A3. Output dei tool lunghi non scaricati — context bloat evitabile

**Problema.** `context_budget.py` ha `offload_tool_output`/`OffloadedOutput`/`drop_reconstructible`
scritti e testati, ma **non collegati**. Un `docker_exec` che stampa molto entra nel contesto
fino a `harness_tool_output_limit` (12.000 caratteri) e ci resta a ogni turno successivo.

**Fix.** Prima della compaction LLM (cara), un passo economico: scaricare su file gli output
di tool lunghi e lasciare in contesto solo riferimento+estratto+checksum (già implementato).
Riduce i token cumulativi senza chiamare il modello.

**Risultato evidente.** Meno token di input per turno → meno costo e meno latenza sui run
lunghi; misurabile con il `context.snapshot` già presente.

### A4. `compute_usage` O(n²) sul run — micro, ma gratis da togliere

**Problema.** `_emit_usage_snapshot` (`runner.py:285`) richiama `compute_usage` su **tutti** i
messaggi a ogni superstep del graph → costo quadratico nella lunghezza del run.

**Fix.** Usare l'ultimo `usage_metadata` incrementale invece di risommare tutto, oppure
memoizzare. Impatto piccolo ma è codice caldo.

### A5. SSE a polling 0,25 s — basso impatto

Ogni stream aperto interroga SQLite 4 volte/secondo. Va bene per la demo; per scala,
`asyncio.Condition`/notify al posto del polling. Priorità bassa.

---

## B. Efficacia — risultati migliori, non solo più veloci

### B1. Chiamate di tool in parallelo

**Problema.** Da verificare se il modello emette tool-call parallele e se il runner le esegue
concorrenti. Se sono seriali, tre letture file diventano tre round-trip.

**Fix.** Abilitare/valorizzare il parallel tool calling (OpenAI lo supporta). Su compiti con
più letture/ricerche indipendenti, taglia i round-trip.

**Risultato evidente.** Meno passi nel trace, run più corti a parità di lavoro.

### B2. Eval set piccolo (20 casi) — l'escalation si regge su questo

**Problema.** L'intero meccanismo router/escalation dipende dal grader, e il grader è calibrato
su 20 casi. Poche categorie = segnale rumoroso = escalation che sbaglia gradino.

**Fix.** Ampliare `evals/cases.json` (40–60 casi, più lingue/difficoltà), ri-calibrare con
`calibrate_grader.py`. Più il grader discrimina, più l'escalation è precisa (paghi il modello
caro solo quando serve).

**Risultato evidente.** Meno escalation inutili → costo medio più basso a parità di qualità,
misurabile sull'eval.

### B3. Prompt caching esplicito

**Problema.** deepagents inserisce `AnthropicPromptCachingMiddleware` (no-op fuori da Claude).
OpenAI fa caching automatico lato server sopra ~1024 token di prefisso stabile; system prompt
(928 tok) + schemi tool (~919 tok) sono un buon prefisso **se restano stabili**. Se l'ordine
dei tool o il prompt cambia fra turni, il caching salta.

**Fix.** Garantire prefisso stabile (ordine tool deterministico, addendum in coda). Su Claude,
verificare che il caching middleware sia attivo per i gradini Anthropic.

**Risultato evidente.** Costo input per turno più basso e TTFT migliore sui turni successivi.

### B4. La verifica «serve sandbox?» resta euristica a parole chiave

`requires_environment_verification` (ora IT+EN) è comunque una lista di verbi. Un obiettivo
«produci X» senza verbo noto salta la verifica. Meglio: lasciar decidere al grader se l'output
richiede prova riproducibile, togliendo del tutto la lista.

### B5. Nessuna memoria strutturata dei run passati

Oltre a `AGENTS.md` (preferenze), l'agente non ha memoria di *cosa ha già fatto* in run
precedenti della stessa sessione se non tramite checkpoint. Per compiti ricorrenti (trigger),
una memoria di esiti/artefatti ridurrebbe rilavoro. Post-demo.

---

## Ordine consigliato (impatto / sforzo)

| # | Intervento | Impatto | Sforzo |
|---|---|---|---|
| 1 | **A1** cache harness per sessione | ~3,7 s/msg | medio |
| 2 | **A2** server interno in-process | ~1 s/skill | medio |
| 3 | **A3** offload output tool lunghi (già scritto) | token/costo run lunghi | basso |
| 4 | **B1** tool-call in parallelo | run più corti | basso-medio |
| 5 | **B2** eval set + ricalibrazione | costo medio ↓ | medio |
| 6 | **A4** compute_usage incrementale | micro | basso |
| 7 | **B3** prefisso prompt stabile / caching | costo input ↓ | basso |

I primi due (A1+A2) da soli tolgono **~4–7 s di tempo morto per messaggio** — la vincita più
visibile in assoluto, e proprio quella che si nota in una demo dal vivo.

---

## Stato implementazione (12 luglio 2026)

Implementati su `feat/pre-demo-harness`:

- **A2 — server interno in-process.** I tool `local_harness` (count_text, glossario, skill_*)
  ora girano nel processo dell'agente (`builtin_tools.py`). Solo i server MCP **esterni**
  restano subprocess. **Build del run: 3,71 s → 0,055 s** (misurato); le skill passano da ~1 s
  a sub-millisecondo. Verificato live: `local_harness` compare come `in-process`, un server
  esterno (`mysql-talk`) convive fuori processo.
- **A1 — cache harness: NON fatta, di proposito.** Misura: `build_harness` senza MCP costa
  **0,046 s**. Dopo A2 il rebuild per-messaggio è già trascurabile; il refactor di caching
  (event-routing mutabile) avrebbe aggiunto rischio per salvare 46 ms. Misurare prima di
  ottimizzare ha evitato lavoro inutile e rischioso.
- **A3 — offload output tool lunghi.** `docker_exec` oltre il limite salva l'integrale in
  `/workspace/.tool_output/<checksum>.txt` (nascosto) e mette in contesto solo estratto +
  riferimento recuperabile. Misura: 54 KB di output → **1.624 caratteri** in contesto (prima
  ~12 KB troncati con perdita). Fallback al troncamento se il filesystem non è scrivibile.
- **B2 — eval set + calibrazione.** `evals/cases.json` **20 → 38 casi** (aggiunti inglese per
  la neutralità linguistica del router, aritmetica facile per il «pavimento» dell'escalation,
  sicurezza/integrità file, e tutti e 7 i tipi di check). Corretto un bug bloccante:
  `calibrate_grader.py` importava `_openai_model`, **rimosso** nel refactor provider — ora usa
  il registry (`build_tier_models`), quindi la ricalibrazione gira di nuovo, anche su Claude o
  provider locali. La ricalibrazione live (`uv run python evals/calibrate_grader.py`) resta un
  passo dell'utente: richiede chiave API e consuma token.

Non ancora fatti (candidati successivi): **B1** tool-call in parallelo, **A4** compute_usage
incrementale, **B3** prefisso prompt stabile per il caching, **B4** verifica delegata al grader.
