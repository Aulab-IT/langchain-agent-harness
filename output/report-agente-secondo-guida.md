# Valutazione del sistema rispetto alla guida sul coding agentico

**Data analisi:** 13 luglio 2026
**Sistema analizzato:** `langchain_harness`, stato corrente del workspace
**Fonte concettuale:** *Guida pratica al coding agentico per sviluppatori*, pp. 4, 8-16.

## Sintesi esecutiva

Il sistema non è una semplice chat con tool: implementa la maggior parte delle componenti minime di un agente e una buona parte di un loop governato. I punti più maturi sono isolamento sandbox, approvazioni, memoria per sessione, trace, rubric, eval e routing di subagent.

Valutazione complessiva: **livello 3 consolidato, livello 4 parziale** nel modello di maturità della guida.

- **Livello 3:** skill, rubric, template, trigger e workflow riutilizzabili sono presenti.
- **Livello 4:** sono presenti molti mattoni (ambienti isolati, memoria, telemetria, gate), ma mancano budget hard, stati terminali coerenti, recovery strutturato e garanzie affidabili sul completamento delle deleghe.
- **Livello 5:** non ancora raggiunto: mancano una policy/identità centralizzata, artifact di verifica immutabili, una gestione costi con enforcement e una piattaforma condivisa multi-team.

La criticità principale non è l'assenza di agenticità: è la differenza tra capacità dichiarata e outcome garantito. Esempi osservati nel sistema:

- una skill può essere creata come file di workspace senza essere installata nel catalogo;
- un subagent `incomplete` può lasciare il run finale con stato tecnico `completed`;
- il router può selezionare un subagent con tool compatibili ma competenza semantica inadatta;
- una configurazione modello non valida può emergere tardi, nel grader, invece di fallire al preflight.

Questi casi impediscono di classificare il loop come pienamente governato.

## Metodo e legenda

Ho confrontato le componenti della guida con codice, configurazione, test e trace locale. La classificazione valuta l'implementazione del runtime, non una certificazione di produzione né l'efficacia di ogni provider/modello.

| Stato | Significato |
|---|---|
| **Implementato** | Meccanismo presente, collegato al runtime e con prova nel codice/test. |
| **Parziale** | Meccanismo presente ma con limiti di copertura, coerenza o enforcement. |
| **Da implementare** | Nessuna garanzia operativa sufficiente nel sistema corrente. |

## 1. Componenti minime del concetto di agente

La guida definisce un agente come un modello che sceglie e usa strumenti in un ciclo verso un obiettivo, osservando gli effetti delle azioni. Le otto componenti minime sono tutte riconoscibili nel sistema, ma non tutte hanno la stessa maturità.

| Componente guida | Stato | Implementazione e prove | Gap da chiudere |
|---|---|---|---|
| **Obiettivo** | **Implementato** | Ogni run riceve un goal, lo valida e lo invia al grafo in `GoalRunner.run`; trigger cron/webhook costruiscono un goal da template e criteri di successo. Vedi `src/agent_harness/runner.py` e `src/agent_harness/server.py::_trigger_goal`. | Collegare il goal a una spec versionata/issue autorevole, non solo a messaggi o template. |
| **Contesto** | **Implementato** | Prompt di sistema, memoria `AGENTS.md`, allegati, skill on-demand, contesto per sessione, compaction e monitor token. Vedi `factory.py`, `context_budget.py`, `context_monitor.py`, `control_store.py::prepare_session_root`. | Ridurre il contesto iniziale; la recente telemetria mostra prompt molto grandi. Applicare retrieval più selettivo e contratti di contesto per subagent. |
| **Tool** | **Implementato** | Tool builtin, filesystem confinato, `docker_exec`, browser, web search, skill, MCP configurabili e `task` per delega. Vedi `builtin_tools.py`, `sandbox.py`, `tools.py`, `mcp_config.py`. | Rendere le capability eseguibili e verificabili: una skill testuale non deve essere presentata come integrazione funzionante se mancano CLI/MCP/API reali. |
| **Osservazione** | **Implementato** | Eventi run/tool/model/grader, audit JSONL, trace UI, output tool e snapshot contesto. Vedi `control_store.py::add_event`, `audit.py`, `RunTracePanel.tsx`. | Separare meglio trace e outcome: preservare artefatti verificati, hash e risultati di test strutturati invece di dipendere anche dal summary testuale. |
| **Memoria** | **Implementato** | Memoria persistente per sessione, checkpoint SQLite, session workspace e capping esplicito. Vedi `memories/AGENTS.md`, `checkpoints.sqlite`, `durable.py`, `control_store.py::cap_session_memory`. | Formalizzare decisioni/tentativi/budget in schema, non solo in memoria libera e messaggi. |
| **Policy** | **Implementato** | Sandbox read-only, capability drop, no-new-privileges, rete disabilitata per default, approvazione tool/rete, permessi read-only per subagent. Vedi `sandbox.py`, `factory.py::docker_exec_requires_approval`, `prompts.py`. | Secret manager reale, allowlist domini, identità agente distinta e policy centralizzata; `.secrets/` è utile ma non sostituisce un vault. |
| **Verifica** | **Implementato** | Verifica ambiente per task produttivi, rubric con safety veto, eval deterministici e canary. Vedi `runner.py::has_successful_verification`, `verification.py`, `evaluation.py::evaluate_checks`. | Rendere obbligatoria una verifica specifica per tipo di outcome; oggi un `docker_exec` con `exit_code=0` può essere troppo generico. |
| **Stop** | **Parziale** | Esistono continuazioni limitate, cancellazione e stati `completed`, `failed`, `cancelled`; `durable.py` definisce anche `incomplete` e retry. | Il server persiste ancora un risultato `completed=False` come stato run `completed`; mancano `BLOCKED_NEEDS_HUMAN`, `BUDGET_EXCEEDED`, `SECURITY_STOP`, `NO_WORK` esposti end-to-end. |

## 2. Anatomia del loop robusto

Questa è la mappa puntuale dei dieci elementi della guida (p. 9).

| Elemento | Stato | Cosa esiste | Cosa manca / rischio |
|---|---|---|---|
| **Trigger** | **Implementato** | Avvio manuale, cron e webhook autenticato; scheduler periodico. Vedi `triggers.py::TriggerScheduler`, endpoint `/api/triggers`. | Trigger da issue/CI e segnali operativi non sono integrazioni native. |
| **Goal source** | **Parziale** | Messaggio utente, template trigger e `success_criteria`. Il payload webhook è trattato come dato non attendibile. | Nessuna fonte autorevole unica per backlog/spec; niente sincronizzazione issue-to-task o versione spec. |
| **Selection policy** | **Parziale** | Routing LLM usa profili, capability, input/output, tool, vincoli, permessi e tier; supporta dipendenze DAG e parallelismo. Vedi `subagent_routing.py::routing_prompt`. | Non c'è una policy deterministica globale di priorità/rischio/costo. Il recente routing verso `presentation-maker` per diagnostica skill dimostra match semantico insufficiente. |
| **Execution boundary** | **Implementato** | Workspace per sessione, container Docker isolato, filesystem read-only, limiti processo, rete temporanea e timeout per comando. Vedi `sandbox.py`. | Container riusato per sessione fino al timeout idle: non è usa-e-getta per tentativo. Nessun worktree Git/ownership file per task parallele. |
| **Observation** | **Implementato** | Trace SSE, eventi persistiti, audit, stato sandbox, uso token/costo, file creati e notifiche. | Log/metriche esterne e health check di sistemi integrati non sono standardizzati. |
| **Verification** | **Parziale** | Grader a rubric, safety veto, eval con check deterministici, verifica ambiente e canary. | Il grader può fallire dopo lavoro corretto se il modello mid non è disponibile; outcome specifico, test protetti e indipendenza maker/checker non sono garantiti in ogni run. |
| **Memory** | **Implementato** | Checkpoint, SQLite, memoria sessione, workspace e state store durevole. | La coda durevole è ancora additiva rispetto al task in memoria del server; recovery dopo restart non è ancora la fonte di verità unica. |
| **Recovery** | **Parziale** | Retry/continuazioni limitate, escalation tier, retry con backoff e dead-letter progettati in `durable.py`, cancellazione e timeout di approvazione/azione. | La strategia alternativa non è classificata per causa; rollback automatico/diagnostic task esplicita non è generalizzata. |
| **Terminal states** | **Parziale** | Nel modello durevole esistono `queued`, `running`, `waiting`, `retry_scheduled`, `completed`, `incomplete`, `failed`, `cancelled`. | API/UI del run comprimono ancora parte degli esiti; manca mappatura esplicita ai terminal state della guida e incoerenza `completed` vs `completed=false`. |
| **Human gates** | **Implementato** | Approva tool sandbox, rete sempre manuale, MCP host-side sempre manuale, user action per OAuth/file/codici; timeout sicuri. Vedi `server.py::approval` e `server.py::interaction`. | Merge, deploy, migrazioni e produzione non hanno ancora gate applicativi perché il sistema non governa direttamente tali workflow. |

## 3. Context, harness e loop engineering

### Context engineering - implementato, da ottimizzare

Il sistema copre bene i mattoni descritti dalla guida:

- istruzioni persistenti in `memories/AGENTS.md`;
- skill copiate nella radice isolata della sessione per ogni run;
- allegati manifestati nel goal;
- offload e limitazione output tool;
- monitor pressione contesto, compaction e UI di dettaglio;
- subagent con contesto/task isolato e risultati iniettati nelle dipendenze.

**Gap prioritario:** stabilire un budget di contesto per ruolo e un caricamento just-in-time. I run recenti mostrano che il contesto di sistema + skill + output tool può diventare dominante. La nuova UI distingue correttamente contesto finale e token cumulativi; serve ora usare la misura per decidere cosa non iniettare.

### Harness engineering - implementato

L'harness è la parte più ricca del sistema:

- provider e tier modello configurabili;
- tool catalogati, MCP dinamici e skill;
- sandbox Docker e rete gated;
- stato, memoria e checkpoint;
- routing/delega di subagent;
- trace, audit, token/costo, notifiche;
- eval, rubric e canary.

**Gap prioritario:** introdurre un preflight di provider/modello e capability. La validazione attuale accetta un nome modello non vuoto ma non garantisce che il provider possa invocarlo; il fallimento può arrivare nel grader e invalidare un run già eseguito.

### Loop engineering - parzialmente governato

Il ciclo interno ha struttura: esegue, raccoglie evidenze, valuta, continua entro limite ed eventualmente sale di tier. Il ciclo esterno ha trigger, store, eventi e cancellazione.

Non è ancora un loop di produzione completo perché non impone:

1. budget hard di token, costo e tempo per run;
2. terminal state semantico coerente in DB, API e UI;
3. recovery deterministico per categoria di errore;
4. verifica artefatti immutabile e separata dal maker;
5. rollback o promozione controllata verso Git/CI/deploy.

## 4. Verifica, sicurezza e osservabilità

### Verifica

**Implementato**

- `RubricGrader` valuta completezza, verifica, aderenza e sicurezza.
- La sicurezza ha veto deterministico sotto soglia.
- `evaluation.py` esegue check su file, testo, tool call e workspace isolato.
- I task che implicano creazione/modifica richiedono almeno una verifica ambiente riuscita.
- Il sistema registra trace, output tool, file e risultato del grader.

**Da implementare**

- Contratti di verifica per classe di task: “skill installata” deve richiedere `skill_list`; “presentazione” deve richiedere file + render; “integrazione Gmail” deve richiedere API reale e consenso; “UI” deve richiedere test browser/screenshot.
- Maker/checker realmente indipendenti: contesto diverso, test/artefatti protetti e, quando utile, modello/provider differente.
- Gating: `subagent.task.incomplete` o `subagent.routing.not_followed` deve impedire `[GOAL_COMPLETE]` e stato `completed`.
- Artifact di verifica immutabili: hash, comando, versione input, output e timestamp salvati come record verificabile.

### Sicurezza

**Implementato**

- Rete disabilitata per default e concessa solo per il comando approvato.
- Container con filesystem read-only, capability rimosse e `no-new-privileges`.
- Prompt distingue dati esterni da istruzioni e impone conferme su azioni irreversibili.
- Caricamenti, tool e path sono confinati; MCP host-side richiede consenso esplicito.
- Comandi sottoposti a review descrittiva prima della conferma.

**Da implementare / rafforzare**

- Vault o integrazione secret manager: `.secrets/` non offre cifratura, rotazione o audit accessi.
- Allowlist di domini/egress e policy per OAuth/API.
- Scansione dipendenze, licenze e vulnerabilità prima di installare pacchetti.
- Boundary di produzione separato da sandbox di sviluppo, con identità/scopi minimi e runbook idempotenti.

### Osservabilità e metriche

**Implementato**

- Eventi persistiti e SSE; trace di tool, modello, subagent, approvazioni e grader.
- Audit JSONL, notifiche e storico paginato.
- Token, costo stimato e contesto finale; canary/eval per confrontare configurazioni.

**Da implementare**

- Dashboard per outcome: success rate per tipo task, regressioni, costo per task accettata, tempo umano, retry rate, failure class.
- Alert esterni e SLO per loop/trigger.
- Correlazione trace -> commit/diff -> CI -> deploy/rollback.

## 5. Requisiti del loop di produzione della guida

| Requisito guida | Stato | Nota |
|---|---|---|
| Ambiente usa-e-getta per tentativo | **Parziale** | Isolamento per sessione sì; container riusato tra tentativi/run finché idle. |
| Trace strutturata | **Implementato** | Event store + SSE + UI trace. |
| Timeout e cancellazione | **Implementato** | Timeout tool, approvazioni, user action, cancellazione run, idle reaper. |
| Budget token e costo | **Parziale** | Misurazione e prezzo sì; limite/enforcement hard no. |
| Deduplicazione e idempotenza | **Parziale** | `DurableStore` implementa chiavi idempotenti, lease e locking; non è ancora il percorso esecutivo unico. |
| Gestione crash/segnali | **Parziale** | Cleanup sandbox e stato/interrupt durevoli; ripresa effettiva post-restart ancora non completa. |
| Isolamento segreti e rete | **Parziale** | Rete e sandbox robuste; vault/rotazione/identità restano mancanti. |
| Artefatti verifica immutabili | **Da implementare** | Eventi e file sono persistiti, ma non sigillati/versionati come evidenza immutabile. |
| Protezione reward hacking | **Parziale** | Rubric, safety veto ed eval aiutano; verifiche specifiche e test protetti non sono universali. |
| Concorrenza e lock | **Implementato** | Semaforo subagent, DAG dipendenze, lock skill e optimistic locking nella coda durevole. |
| Osservabilità e allarmi | **Parziale** | Osservabilità locale buona; alert/SLO operativi incompleti. |
| Gate umani e rollback | **Parziale** | Gate umani presenti; rollback/CI/deploy workflow assenti. |

## 6. Maturità stimata

| Livello guida | Stato | Motivazione |
|---|---|---|
| 0 - Chat occasionale | Superato | Repository, tool, sandbox e memoria sono integrati. |
| 1 - Agent interattivo | Superato | L'agente lavora nel workspace con approvazioni e trace. |
| 2 - Repository agent-ready | In buona parte | Istruzioni, comandi, test, sandbox e contesto sono presenti; le spec non sono ancora una fonte di lavoro governata. |
| 3 - Workflow riutilizzabili | **Raggiunto** | Skill, subagent, rubric, eval, trigger e pannelli di controllo esistono. |
| 4 - Loop governati | **Parziale** | Molti componenti presenti, ma budget, outcome, recovery, terminal state e isolamento per tentativo non sono affidabili end-to-end. |
| 5 - Piattaforma interna | Non raggiunto | Nessuna policy/identità centralizzata, cost management con enforcement, artifact immutabili o integrazione CI/deploy condivisa. |

## 7. Roadmap prioritaria

### P0 - Correttezza del loop

1. **Stati terminali reali.** Persistire `incomplete` come stato run distinto; introdurre `blocked_needs_human`, `failed_verification`, `budget_exceeded`, `security_stop`, `no_work` in API, UI e trigger.
2. **Completamento delle deleghe.** Se un task pianificato è `incomplete`, `failed` o `not_followed`, il root deve riprovare/sostituire/degradare esplicitamente; non può chiudere come completato.
3. **Skill atomiche.** “Crea skill” è completo solo dopo `skill_create`/`skill_write`, validazione front matter, eval e presenza in `skill_list`. I file in `/workspace` sono bozze, non skill installate.
4. **Preflight provider/modello.** Probe per ogni tier realmente usato prima di routing, tool e grader; errore leggibile e nessun run parziale su modello inesistente.

### P1 - Governance di costo e recovery

5. **Budget hard per run.** Limiti configurabili per token cumulativi, costo, durata, tool call e subagent; stop con `BUDGET_EXCEEDED` e trace della causa.
6. **Recovery per causa.** Tassonomia errore -> retry con backoff, cambio modello/provider, diagnosi, attesa umana oppure stop; niente retry identico cieco.
7. **Durable queue come fonte di verità.** Far passare tutti i run/trigger/interrupt attraverso `DurableStore`, con ripresa post-restart e dead-letter visibile.

### P2 - Evidenze e ambiente di produzione

8. **Verifier contrattuali e artifact firmati.** Ogni tipo task dichiara prove minime; salvare hash di input/output, comando, risultato e versione ambiente.
9. **Maker/checker separati.** Workspace o worktree distinti, checker read-only, test protetti e rubric per domain.
10. **Git/CI/deploy boundary.** Branch/worktree per task, PR/review, CI status, ambiente preview, gate umano per merge/deploy/migrazioni e rollback documentato.

### P3 - Sicurezza e piattaforma

11. **Secret manager, identity e egress policy.** Token scoped, rotazione/revoca, audit accessi e allowlist domini.
12. **Misurazione outcome.** KPI per task accettata: lead time, costo, retry, regressioni, tempo umano e qualità review; usare eval/canary per decidere cambi di harness/modello.

## Conclusione

Il sistema possiede già l'architettura di un agente avanzato: obiettivo, contesto, tool, osservazione, memoria, policy, verifica e loop sono presenti. Il passaggio necessario non è aggiungere altra autonomia generica; è rendere deterministiche le promesse che il sistema già espone.

La priorità è quindi: **prima stati e verifiche affidabili, poi budget/recovery, infine integrazione di delivery e piattaforma**. Solo dopo questi passi il livello 4 della guida può essere considerato raggiunto in modo operativo.
