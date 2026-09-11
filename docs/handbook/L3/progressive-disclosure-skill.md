# L3 · Progressive disclosure delle skill

**Unità:** stadio 2 · assemblaggio del contesto → [2.2](../L2_UNITA.md#22--progressive-disclosure-delle-skill)

*Le skill sono esposte al modello per nome e descrizione; il corpo `SKILL.md` entra nel
contesto solo quando l'agente decide di usarla. Installarle da fonti esterne è un'operazione
con superficie d'attacco reale, e il modulo la tratta come tale.*

Due comportamenti in una unità, con pesi opposti: la disclosure è semplice, l'installazione
è la parte densa.

---

## Disclosure

Il grafo riceve il **percorso** delle skill, non il loro contenuto:

```python
skills=[f"{SANDBOX_SKILLS_MOUNT}/"],
```

**Evidenza:** `factory.py · L1039`.

Il costo in contesto è quindi proporzionale al numero di skill (nome + descrizione), non
alla loro lunghezza. Una skill da 400 righe pesa quanto una da 10 finché non viene invocata.

Le skill sono leggibili ma **non scrivibili** dal run —
vedi [confinamento del filesystem](confinamento-filesystem.md#2--lista-di-permessi-con-deny-finale).
Le modifiche fatte dal pannello valgono dal run successivo, perché
`prepare_session_root` ricopia la cartella da zero a ogni run
(`control_store.py · L1093–1094`).

### Dove vivono, e perché in tre posti

Lo stesso catalogo compare sotto tre percorsi diversi, ed è facile confonderli:

| Percorso | Cos'è | Chi lo scrive |
|---|---|---|
| `.agents/skills/` nel progetto | sorgente unica, percorso dello standard Agent Skills | l'utente, i tool `skill_*`, il Control Center |
| `<radice di sessione>/skills/` | copia rifatta a ogni run | `prepare_session_root` |
| `/skills` nel container | mount in sola lettura della sorgente | il manager della sandbox |

La sorgente è `.agents/skills/`, non una cartella `skills/` in radice: lo dice
`SKILLS_SUBPATH`, e sia la configurazione sia il mount della sandbox partono da lì
invece di ricostruire il percorso a mano.

**Evidenza:** `config.py · L22–30` (`SKILLS_SUBPATH`), `config.py · L180–184` (`skills_dir`),
`config.py · L190–194` (`ensure_directories`), `sandbox.py · L389` (il mount).

Sono **dati dell'utente, non sorgenti del progetto**: ogni installazione ha il proprio
catalogo e il repository non lo versiona (`.gitignore`). Un clone appena fatto parte senza
nessuna skill, e `ensure_directories` crea la cartella vuota al primo avvio.

---

## Formato e validazione

`SKILL.md` = frontmatter YAML + corpo Markdown. Il parsing è difensivo su tutta la linea:
YAML illeggibile, frontmatter non-dizionario o assente producono `{}` invece di
un'eccezione (`skills.py · L41–54`).

`validate_skill` verifica lo standard Agent Skills e **ritorna una lista di errori** invece
di sollevare (`skills.py · L57–80`), così la UI può mostrare tutti i problemi insieme
invece che uno per volta.

| Regola | Motivo |
|---|---|
| `name` presente, ≤ `_MAX_NAME` | — |
| `name` solo `a-z`, cifre, trattini singoli, senza trattino iniziale/finale/doppio | è anche un nome di cartella |
| `name` **coincide con la cartella** | impedisce che il nome dichiarato e quello reale divergano |
| `description` presente, non vuota, ≤ `_MAX_DESCRIPTION` | è ciò che il modello legge per decidere se aprirla |
| `compatibility` ≤ `_MAX_COMPATIBILITY` | — |

La regola sul nome che deve coincidere con la cartella è la più importante per la sicurezza:
è ciò che rende il nome un identificatore affidabile invece di un'etichetta arbitraria.

---

## Confinamento dei percorsi

Due funzioni, due garanzie diverse, entrambe necessarie.

**`confine_to_directory`** — il risultato deve essere un **figlio diretto** di `base_dir`:
`candidate.parent != base` → `ValueError` (`skills.py · L120–127`). Usata per le cartelle
skill, che non possono essere annidate.

**`_resolve_within`** — accetta percorsi annidati ma esclude traversal e symlink
(`skills.py · L201–214`). Il docstring cita la regola applicata: `resolve()` **poi**
`is_relative_to(root)`, nell'ordine giusto per battere sia il traversal `../` sia le fughe
via symlink. Rifiuta anche il byte NUL e il caso `candidate == base`.

`_skill_dir` applica **entrambe** le difese: prima la regex sul nome, poi il confinamento
(`skills.py · L129–134`). Il commento lo dichiara: «difesa oltre alla regex del name». Se la
regex avesse un buco, il confinamento regge lo stesso.

---

## Installazione da fonti esterne

Quattro sorgenti: archivio, URL, git, registry (`skills.py · L502–612`). Tutte convergono
sulle stesse difese.

### Guardia SSRF

`_guard_external_host` (`skills.py · L339–360`):

1. schema `http`/`https` — nient'altro;
2. host risolvibile;
3. **ogni** indirizzo risolto controllato: link-local, multicast, reserved, unspecified →
   rifiuto.

Il docstring dichiara esplicitamente il confine scelto: *non* blocca loopback e RFC1918,
perché questo è un harness locale in cui l'operatore incolla URL espliciti (anche
`localhost` per i test), mentre il bersaglio vero — i metadati cloud su `169.254.169.254`,
coperto da link-local — resta chiuso (`skills.py · L342–345`).

Decisione documentata con la sua motivazione: il tipo di cosa che un audit deve poter
valutare invece di dover indovinare.

### Redirect

`_GuardedRedirectHandler` ri-applica la guardia **a ogni hop** (`skills.py · L362–376`).
Senza questo, un URL iniziale innocuo che redirige a `169.254.169.254` passerebbe: la
guardia sul solo primo URL è una guardia che non protegge.

### Download

`_download_bytes` legge `max_bytes + 1` e rifiuta se supera (`skills.py · L378–387`). Legge
un byte in più apposta: è l'unico modo di distinguere «esattamente al limite» da «oltre il
limite» senza fidarsi di `Content-Length`.

### Estrazione blindata

`_extract_archive` (`skills.py · L402–440`) rifiuta:

| Cosa | zip | tar |
|---|---|---|
| symlink | modo `0o120000` in `external_attr` | `member.issym()` |
| hardlink | — | `member.islnk()` |
| file speciali | — | `not member.isfile()` |
| troppi file | `count > _MAX_ARCHIVE_FILES` | idem |
| troppi byte | `total > _MAX_TOTAL_BYTES` | idem |
| traversal | `_resolve_within(dest, info.filename)` | `_resolve_within(dest, member.name)` |

I contatori sono incrementati **prima** del controllo e il controllo avviene **prima** di
scrivere: una zip bomb viene fermata durante l'iterazione, non dopo aver riempito il disco.

Il formato è determinato per **firma dei byte**, non per estensione: `PK\x03\x04` → zip,
`\x1f\x8b` → tar.gz. L'estensione dell'URL è solo un fallback
(`skills.py · L389–400`).

### Scrittura atomica

`_atomic_write` (`skills.py · L150–173`) evita di lasciare una skill mezza scritta se il
processo muore a metà.

---

## Tracciabilità

Ogni installazione è registrata in un log di eventi (`skills.py · L291–337`):
`record_skill_event` e `list_skill_installs`. Sapere *da dove* è arrivata una skill è parte
del comportamento, non un extra — una skill è codice che finisce nel prompt.

---

## Riepilogo evidenza

| Sito | Righe | Ruolo |
|---|---|---|
| `src/agent_harness/factory.py` | L1039 | disclosure per percorso, non per contenuto |
| `src/agent_harness/skills.py` | L41–54 | parsing difensivo del frontmatter |
| `src/agent_harness/skills.py` | L57–80 | validazione con lista di errori |
| `src/agent_harness/skills.py` | L120–134 | confinamento delle cartelle skill |
| `src/agent_harness/skills.py` | L150–173 | scrittura atomica |
| `src/agent_harness/skills.py` | L201–214 | risoluzione annidata anti-traversal/symlink |
| `src/agent_harness/skills.py` | L291–337 | log delle installazioni |
| `src/agent_harness/skills.py` | L339–360 | guardia SSRF |
| `src/agent_harness/skills.py` | L362–376 | guardia sui redirect |
| `src/agent_harness/skills.py` | L378–400 | limite di download e sniffing per firma |
| `src/agent_harness/skills.py` | L402–440 | estrazione blindata |
| `src/agent_harness/skills.py` | L502–612 | le quattro sorgenti di installazione |
| `src/agent_harness/control_store.py` | L1093–1094 | ricopia a ogni run |

**Test:** `tests/test_skills.py`.

---

## Note per chi modifica

- **Non spostare la guardia SSRF fuori dal redirect handler.** Controllare solo il primo URL
  è equivalente a non controllare.
- **Non passare a `extractall()`.** L'estrazione manuale esiste per applicare i controlli
  membro per membro; `extractall` li salterebbe tutti.
- **Se allarghi la guardia SSRF**, aggiorna il docstring a `skills.py · L342–345`: quel
  commento è il posto in cui è scritto *cosa è deliberatamente permesso*, ed è ciò su cui si
  basa chi verifica.
- **Aggiungere una sorgente di installazione** → deve passare da `_download_bytes` e
  `_extract_archive`, non reimplementarli.
