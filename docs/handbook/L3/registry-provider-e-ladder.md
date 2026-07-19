# L3 · Registry dei provider e ladder dei modelli

**Unità:** stadio 1 · configurazione e composizione → [1.2](../L2_UNITA.md#12--registry-dei-provider-e-ladder-dei-modelli)

*Nessun punto del codice applicativo sa quale vendor sta parlando. Ogni ruolo — gradino
della ladder, grader, revisore, ricercatore — chiede al registry il modello del proprio
descriptor; il vendor resta confinato nell'adattatore, le capacità sono dichiarate e non
dedotte dal nome, e gli errori arrivano al chiamante già normalizzati.*

---

## Il principio, scritto nel modulo

> «Non basta essere compatibile solo perché espone `/v1`: le differenze si dichiarano nelle
> capability e si verificano con un capability probe, non si danno per scontate.»

**Evidenza:** `providers.py · L12–13`.

È il criterio che spiega tutte le scelte sotto: la compatibilità non si assume mai.

---

## Capacità dichiarate

`ModelCapabilities` elenca cosa un modello sa fare. Il docstring dice il perché: *«un
routing che manda structured output a un modello che non lo supporta fallisce a metà run;
qui la capacità è nota a startup e la si può rifiutare prima di partire»*
(`providers.py · L36–43`).

**Evidenza:** `providers.py · L36–60`.

`context_window`, `max_output_tokens`, e poi otto flag booleani: `supports_tools`,
`supports_parallel_tools`, `supports_structured_output`, `supports_reasoning`,
`supports_prompt_caching`, `supports_encrypted_reasoning`, `supports_usage_reporting`,
`supports_model_listing`.

Il punto non sono i flag: è **quando** si sa. A startup, non a metà run.

### Il probe

`CapabilityProbeResult` tiene separato ciò che è **dichiarato** da ciò che è stato
**verificato live** (`providers.py · L463–477`). `declared_probe` costruisce il risultato
dalle sole dichiarazioni (`providers.py · L479–490`), mentre `unsupported()` risponde `True`
solo se la verifica live ha smentito la dichiarazione — non se semplicemente non è stata
fatta (`providers.py · L475–476`).

Distinzione a tre valori, non booleana: *dichiarato supportato*, *verificato non
supportato*, *non verificato*. Il preflight (`model_preflight.py`) la usa per fallire prima
di partire invece che a metà.

---

## Identità del modello

`ModelDescriptor`: provider, nome, capacità, tipo di esecuzione (`cloud` o locale),
`pricing_key`, `reasoning_effort` (`providers.py · L119–136`).

`pricing_key` è **distinto dal nome vendor** apposta: collega il descriptor al catalogo
prezzi senza costringere un alias di configurazione a coincidere col nome tecnico del
modello (`providers.py · L122–124`). `resolved_pricing_key()` fa il fallback al nome quando
non è impostato.

---

## Tassonomia degli errori

Questa è la parte che rende l'astrazione utile invece che decorativa.

```python
class ProviderError(Exception):
    """Il codice del runner reagisce al `kind` (retry su rate_limit/timeout,
    escalation su context_length, stop su auth) senza conoscere le eccezioni
    specifiche di ciascun SDK."""
```

**Evidenza:** `providers.py · L151–164`.

| `kind` | Retryable | Reazione prevista |
|---|---|---|
| `rate_limit` | ✅ | retry |
| `timeout` | ✅ | retry |
| `unavailable` | ✅ | retry |
| `context_length` | ❌ | escalation a un gradino con finestra maggiore |
| `auth` | ❌ | stop |
| `bad_request` | ❌ | stop |
| `unknown` | ❌ | stop |

Il fallback `_classify_by_text` mappa un'eccezione qualunque leggendo messaggio e nome
classe (`providers.py · L185–205`). Non conosce gli SDK: copre i casi ricorrenti (429,
timeout, 401/403, context length, 502/503, 400) per **qualunque** provider HTTP. Gli
adattatori possono raffinare, nessuno è obbligato a farlo per funzionare.

Gli adattatori cloud sollevano `auth` prima ancora di provare, se la chiave manca:
`providers.py · L250` (OpenAI), `providers.py · L284` (Anthropic).

---

## Il contratto dell'adattatore

Tre metodi, definiti come `Protocol` (`providers.py · L166–183`):

| Metodo | Responsabilità |
|---|---|
| `build_chat_model` | costruisce il client del vendor dal descriptor |
| `normalize_usage` | traduce l'usage del vendor in `ModelCallUsage` con costo normalizzato |
| `classify_error` | traduce l'eccezione del vendor in `ProviderError` |

Adattatori registrati di default: OpenAI, Anthropic, e due locali OpenAI-compatibili —
Ollama e MLX, che condividono `_OpenAICompatibleLocalAdapter` (`providers.py · L296–353`,
`providers.py · L418–426`).

Esiste anche `ConformanceProviderAdapter` (`providers.py · L355–379`): un adattatore di
prova per verificare che il contratto sia rispettabile senza chiamare un vendor reale.

---

## Il registry

`ProviderRegistry` mappa nome → adattatore (`providers.py · L381–416`). Il docstring dichiara
esplicitamente cosa sostituisce: *«Rimuove il `ChatOpenAI` cablato nella factory»*
(`providers.py · L383–386`).

Un provider non registrato produce un `ProviderError("bad_request", ...)`, non un
`KeyError` (`providers.py · L399–402`): anche il fallimento di configurazione entra nella
stessa tassonomia.

Istanza unica in `factory.py · L82`.

---

## La ladder

Tre gradini — `low`, `mid`, `high` (`middleware.py · L52–58`) — con un solo punto di
mutazione.

```python
class TierLadder:
    """Muta in un punto solo — `escalate()`, chiamato dal runner quando
    l'iterazione non ha prodotto progresso."""
```

**Evidenza:** `middleware.py · L98–119`.

Il grafo parte dal gradino **basso** (`factory.py · L1032–1035`): un run che non apre nessun
turno costa poco. Il router lo scavalca a ogni chiamata.

### Precedenza delle decisioni

`decide_tier` applica un'autorità crescente (`middleware.py · L141–171`):

```
default  <  escalation  <  session_override  <  message_override
```

Il gradino raggiunto per escalation diventa il nuovo default, ma un override esplicito
della sessione lo scavalca, e un override nel singolo messaggio scavalca anche quello. La
`RouteDecision` porta con sé il campo `source` (`middleware.py · L83–87`), quindi la trace
dice **perché** è stato scelto un gradino, non solo quale.

---

## Riepilogo evidenza

| Sito | Righe | Ruolo |
|---|---|---|
| `src/agent_harness/providers.py` | L36–60 | capacità dichiarate |
| `src/agent_harness/providers.py` | L119–136 | identità del modello e chiave di listino |
| `src/agent_harness/providers.py` | L151–164 | tassonomia degli errori |
| `src/agent_harness/providers.py` | L166–183 | contratto dell'adattatore |
| `src/agent_harness/providers.py` | L185–205 | classificazione di fallback |
| `src/agent_harness/providers.py` | L231–294 | adattatori cloud |
| `src/agent_harness/providers.py` | L296–353 | adattatori locali |
| `src/agent_harness/providers.py` | L381–426 | registry e default |
| `src/agent_harness/providers.py` | L463–490 | capability probe a tre valori |
| `src/agent_harness/middleware.py` | L52–58 | definizione dei gradini |
| `src/agent_harness/middleware.py` | L83–119 | decisione e ladder |
| `src/agent_harness/middleware.py` | L141–171 | precedenza degli override |
| `src/agent_harness/model_errors.py` | L58–110 | errori transitori e dettagli |
| `src/agent_harness/model_preflight.py` | — | rifiuto prima di partire |

**Test:** `tests/test_providers.py`, `tests/test_model_errors.py`,
`tests/test_model_preflight.py`, `tests/test_middleware.py`, `tests/test_provider_settings.py`.

---

## Note per chi modifica

- **Aggiungere un provider** → un adattatore che implementa i tre metodi del Protocol, più
  la registrazione in `default_registry`. Nient'altro nel codice applicativo cambia. Se
  cambia, l'astrazione ha una falla lì.
- **Non dedurre capacità dal nome del modello.** È esattamente ciò che il modulo esiste per
  evitare (`providers.py · L12–13`).
- **Aggiungere un `kind` di errore** → va deciso il comportamento del runner insieme al
  `kind`, altrimenti finisce in `unknown` e si comporta come non-retryable.
- Il `source` di `RouteDecision` è consumato dalla trace: toglierlo rende impossibile
  spiegare a posteriori perché un run ha usato un modello costoso.
