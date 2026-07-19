# L3 · Contratto di evidenza e gate di delivery

**Unità:** stadio 6 · persistenza e proiezione → [6.2](../L2_UNITA.md#62--contratto-di-evidenza-e-gate-di-delivery)

*Alla fine di un run l'harness produce un manifest hashato di ciò che è stato fatto: stato
terminale, artefatti con checksum, comandi eseguiti con esito, verifiche, provenienza del
codice. Un checker indipendente lo ricontrolla su una copia read-only, e l'approvazione
umana di delivery è legata all'hash di quel manifest specifico.*

Il principio: **l'agente non è la fonte di verità su ciò che ha fatto**.

---

## Cosa entra nel manifest

`build_evidence_manifest` (`evidence.py · L357–437`) raccoglie da fonti indipendenti dal
racconto del modello:

| Sezione | Origine | Evidenza |
|---|---|---|
| Artefatti | filesystem: path, `sha256`, dimensione | `evidence.py · L254–283` |
| Comandi | eventi della trace, con `exit_code` estratto | `evidence.py · L285–331` |
| Verifiche | eventi del grader | `evidence.py · L333–355` |
| Provenienza | git: commit, branch, stato, versione pacchetto, piattaforma | `evidence.py · L207–238` |
| Requisiti | check calcolati sui dati sopra | `evidence.py · L376–437` |

L'esito di un comando non è ciò che il modello dice: è `exit_code` estratto dall'output con
una regex (`evidence.py · L32`). `sandbox_passed` è vero solo se esiste un `docker_exec`
effettivamente passato (`evidence.py · L373`).

Gli artefatti mancanti sono raccolti a parte (`missing_artifacts`): un artefatto dichiarato
e non trovato è un dato, non un silenzio.

---

## Redazione dei segreti

Il manifest viene salvato e mostrato, quindi passa da `_redact_sensitive`
(`evidence.py · L52–55`), con due pattern:

- coppie chiave-valore per `api_key`, `token`, `secret`, `password`, `authorization`
  (`evidence.py · L33–36`);
- token `Bearer` (`evidence.py · L37`).

Un comando che conteneva una chiave non deve diventare un artefatto permanente che la
contiene.

---

## Hash canonico

`_canonical_json` (`evidence.py · L57–64`) serializza in forma canonica prima di calcolare
lo `sha256`. Senza canonicalizzazione, due serializzazioni dello stesso contenuto — ordine
delle chiavi diverso, spaziatura diversa — darebbero hash diversi, e il manifest non sarebbe
verificabile.

`SCHEMA_VERSION = 2` (`evidence.py · L20`) versiona il formato.

---

## Verifica dell'integrità

`verify_evidence_manifest` (`evidence.py · L439–475`) ricalcola tutto:

1. **il manifest stesso** — hash ricalcolato vs dichiarato;
2. **ogni artefatto** — path confinato, file esistente, `sha256` **e** dimensione uguali.

Il controllo del path usa `resolve()` + `is_relative_to(root)` + `candidate != root`, la
stessa disciplina delle [skill](progressive-disclosure-skill.md#confinamento-dei-percorsi).
Un `OSError` in lettura non solleva: diventa un check fallito
(`evidence.py · L458–462`). Una verifica che può crashare non è una verifica.

Confrontare **sia** hash **sia** dimensione è ridondante in teoria e gratuito in pratica.

---

## Il checker indipendente

```python
def run_independent_checker(bundle_root: Path) -> EvidenceCheckerResult:
    """Controlla il bundle senza ricevere accesso al workspace scrivibile del maker."""
```

**Evidenza:** `evidence.py · L536–568`.

È la parte che rende l'unità qualcosa di più di un log. Il checker:

1. legge il manifest **dal bundle**, non dal workspace;
2. verifica l'integrità contro `bundle_root/artifacts`, una copia;
3. controlla che il contratto delle evidenze sia soddisfatto;
4. **verifica che il bundle sia davvero read-only** — controlla i bit `S_IWUSR | S_IWGRP |
   S_IWOTH` su ogni path, ricorsivamente (`evidence.py · L541–544`).

Il quarto punto è quello che chiude il cerchio: un bundle ancora scrivibile è un bundle di
cui non ci si può fidare, perché chi lo ha prodotto potrebbe averlo modificato dopo la
verifica. Il check `read_only_bundle` fallisce e con lui l'intero risultato.

Separazione maker/checker applicata a livello di filesystem, non di buone intenzioni.

---

## Il gate di delivery

`assess_delivery_readiness` (`evidence.py · L570–647`) combina quattro condizioni:

| Check | Cosa richiede |
|---|---|
| `integrity` | evidenze integre |
| `independent_checker` | checker superato |
| CI | `ci_status` ∈ {success, passed, succeeded} |
| approvazione | decisione `approved` **con lo stesso `manifest_sha256`** |

L'ultima è la più importante:

```python
approved = bool(
    gate
    and gate.get("decision") == "approved"
    and gate.get("manifest_sha256") == manifest.manifest_sha256
)
```

**Evidenza:** `evidence.py · L581–586`.

L'approvazione vale **per quel manifest**, non per il run. Se qualcosa cambia dopo
l'approvazione, il manifest ha un hash diverso e l'approvazione non si applica più. Non
esiste un'approvazione «in bianco» che copra modifiche successive.

### L'endpoint

`POST /api/runs/{run_id}/delivery-gate` (`server.py · L2425–2483`) rifiuta di approvare se:

- il run non è `completed` → 409 (`server.py · L2448–2452`);
- integrità non valida, oppure checker assente o fallito → 409
  (`server.py · L2453–2458`).

Un umano **non può** approvare un run le cui evidenze non tornano. Il gate non è un veto
opzionale sopra una decisione automatica: è una condizione che si aggiunge a quelle
automatiche.

`requires_human_gate` determina se il gate si applica (`server.py · L2436–2437`);
`delivery_boundary` (`evidence.py · L240–252`) decide dall'obiettivo e dalla provenienza se
il run ha una rilevanza di delivery. Un run che non produce niente di consegnabile non
chiede un'approvazione inutile.

---

## Riepilogo evidenza

| Sito | Righe | Ruolo |
|---|---|---|
| `src/agent_harness/evidence.py` | L20–37 | versione schema, stati terminali, pattern di redazione |
| `src/agent_harness/evidence.py` | L52–64 | redazione e JSON canonico |
| `src/agent_harness/evidence.py` | L73–174 | modelli del manifest |
| `src/agent_harness/evidence.py` | L207–252 | provenienza e confine di delivery |
| `src/agent_harness/evidence.py` | L254–355 | artefatti, comandi, verifiche |
| `src/agent_harness/evidence.py` | L357–437 | costruzione del manifest |
| `src/agent_harness/evidence.py` | L439–475 | verifica dell'integrità |
| `src/agent_harness/evidence.py` | L477–534 | creazione del bundle |
| `src/agent_harness/evidence.py` | L536–568 | checker indipendente e read-only |
| `src/agent_harness/evidence.py` | L570–647 | valutazione della prontezza |
| `src/agent_harness/server.py` | L2389–2423 | lettura delle evidenze |
| `src/agent_harness/server.py` | L2425–2483 | gate di delivery |

**Test:** `tests/test_evidence.py`, `tests/test_server.py`.

---

## Note per chi modifica

- **Non rimuovere il check `read_only_bundle`.** È l'unica cosa che distingue un checker
  indipendente da un secondo sguardo sugli stessi file scrivibili.
- **Non slegare l'approvazione dal `manifest_sha256`.** Diventerebbe un'approvazione in
  bianco.
- **Aggiungere un campo al manifest** → cambia l'hash: va alzato `SCHEMA_VERSION` e va
  verificato che i manifest salvati prima restino leggibili.
- **La redazione precede il calcolo dell'hash** e deve restare così: oggi avviene durante la
  raccolta dei comandi (`evidence.py · L317`, `evidence.py · L319`), mentre l'hash è
  calcolato alla fine (`evidence.py · L435`). Invertire l'ordine produrrebbe un manifest
  redatto che non corrisponde al proprio hash.
