"""Contratti canonici di usage e costo (Fase 0 del piano evolutivo).

Un solo posto definisce cosa significa "token" e cosa significa "costo", così che
CLI, API, UI, eval e canary parlino la stessa lingua. Prima di questo modulo
``compute_usage`` misurava il contesto dell'ultima chiamata mentre l'eval sommava
tutti i messaggi: due numeri diversi chiamati entrambi "token".

Regole non negoziabili:

- **il costo è ``Decimal``, mai ``float``.** Un ledger economico non può accumulare
  l'errore di arrotondamento binario di ``float``;
- **tre grandezze distinte**, non un unico "input_tokens": la dimensione del
  contesto all'ultima chiamata, la somma cumulativa degli input e la somma degli
  output sono misure diverse e vanno tenute separate;
- **il prezzo è versionato nel tempo.** Un run storico si valuta con il listino in
  vigore quando è stato eseguito, mai con i prezzi correnti;
- **provider locale non è "gratis":** il costo fatturato può essere zero, ma resta
  una stima separata (energia, hardware, tempo) che non va confusa con lo zero API.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal

ExecutionKind = Literal["cloud", "local"]
UsageSource = Literal["provider", "estimated", "absent"]

# Un milione: i prezzi sono espressi in valuta per milione di token, come i listini
# pubblici dei provider. Tenerlo esplicito evita di sbagliare gli zeri nel costo.
TOKENS_PER_PRICE_UNIT = Decimal(1_000_000)


def _money(value: Any) -> Decimal:
    """Converte in ``Decimal`` passando dalla stringa: ``Decimal(0.1)`` erediterebbe
    l'errore binario del ``float``, ``Decimal("0.1")`` no."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


@dataclass(frozen=True)
class PriceEntry:
    """Listino di un modello valido in una finestra temporale.

    ``valid_from``/``valid_to`` sono ISO-8601 (``valid_to`` vuoto = ancora in vigore).
    Prezzi in valuta per milione di token. ``version`` identifica il listino così che
    ogni ``ModelCallUsage`` possa dichiarare con quale prezzo è stato calcolato.
    """

    provider: str
    model: str
    input_price: Decimal
    output_price: Decimal
    cached_input_price: Decimal = Decimal(0)
    reasoning_price: Decimal = Decimal(0)
    currency: str = "USD"
    source: str = "config"
    version: str = "v1"
    valid_from: str = ""
    valid_to: str = ""

    def covers(self, when: str) -> bool:
        if self.valid_from and when < self.valid_from:
            return False
        return not (self.valid_to and when >= self.valid_to)


@dataclass(frozen=True)
class ModelCallUsage:
    """Usage e costo canonici di una singola chiamata al modello.

    Immutabile: una chiamata è un fatto accaduto, non si aggiorna. Le aggregazioni
    (per run, sessione, provider) si costruiscono sommando queste, mai ricalcolando
    a ritroso con prezzi nuovi.
    """

    provider: str
    model: str
    execution_kind: ExecutionKind
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    input_cost: Decimal = Decimal(0)
    output_cost: Decimal = Decimal(0)
    reasoning_cost: Decimal = Decimal(0)
    effective_local_cost: Decimal | None = None
    currency: str = "USD"
    pricing_version: str = ""
    usage_source: UsageSource = "provider"

    @property
    def total_tokens(self) -> int:
        # reasoning_tokens è un sottoinsieme degli output nei provider che lo espongono
        # (OpenAI Responses): non va risommato o si conterebbe due volte.
        return self.input_tokens + self.output_tokens

    @property
    def billable_tokens(self) -> int:
        """Token che concorrono al costo cloud: gli output più gli input non in cache.

        Per un provider locale (nessuna fattura) resta un conteggio informativo.
        """
        return max(0, self.input_tokens - self.cached_input_tokens) + self.output_tokens

    @property
    def total_cost(self) -> Decimal:
        return self.input_cost + self.output_cost + self.reasoning_cost

    def to_row(self) -> dict[str, Any]:
        """Forma serializzabile per DB/evento: i ``Decimal`` diventano stringhe, non
        ``float``, per non reintrodurre l'errore binario appena eliminato."""
        return {
            "provider": self.provider,
            "model": self.model,
            "execution_kind": self.execution_kind,
            "input_tokens": self.input_tokens,
            "cached_input_tokens": self.cached_input_tokens,
            "output_tokens": self.output_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "total_tokens": self.total_tokens,
            "billable_tokens": self.billable_tokens,
            "input_cost": str(self.input_cost),
            "output_cost": str(self.output_cost),
            "reasoning_cost": str(self.reasoning_cost),
            "total_cost": str(self.total_cost),
            "effective_local_cost": (
                None if self.effective_local_cost is None else str(self.effective_local_cost)
            ),
            "currency": self.currency,
            "pricing_version": self.pricing_version,
            "usage_source": self.usage_source,
        }


class PricingCatalog:
    """Listini versionati per (provider, modello), risolti a una data.

    Non tiene prezzi correnti sovrascrivibili: ogni entry porta la propria finestra
    di validità, così valutare un run del mese scorso non usa il prezzo di oggi.
    """

    def __init__(self, entries: list[PriceEntry] | None = None) -> None:
        self._entries: list[PriceEntry] = list(entries or [])

    def add(self, entry: PriceEntry) -> None:
        self._entries.append(entry)

    def entries(self) -> list[PriceEntry]:
        return list(self._entries)

    def resolve(self, provider: str, model: str, *, when: str | None = None) -> PriceEntry | None:
        when = when or datetime.now(UTC).isoformat()
        matches = [
            entry
            for entry in self._entries
            if entry.provider == provider and entry.model == model and entry.covers(when)
        ]
        if not matches:
            return None
        # Se due listini si sovrappongono, vince quello iniziato più tardi: è il più
        # recente ad applicarsi, come una correzione di prezzo entrata in vigore dopo.
        return max(matches, key=lambda entry: entry.valid_from)


def compute_costs(
    *,
    input_tokens: int,
    cached_input_tokens: int,
    output_tokens: int,
    reasoning_tokens: int,
    price: PriceEntry,
) -> tuple[Decimal, Decimal, Decimal]:
    """Costi (input, output, reasoning) da conteggi token e listino.

    Gli input in cache si pagano al prezzo cache (spesso più basso), il resto al
    prezzo input, così non si conta il token in cache due volte. ``reasoning_cost``
    resta zero se il listino non fissa un prezzo reasoning distinto: nei provider che
    espongono il reasoning i suoi token sono già dentro gli output e già fatturati.
    """
    non_cached = max(0, input_tokens - cached_input_tokens)
    input_cost = (
        _money(non_cached) * price.input_price
        + _money(cached_input_tokens) * price.cached_input_price
    ) / TOKENS_PER_PRICE_UNIT
    output_cost = _money(output_tokens) * price.output_price / TOKENS_PER_PRICE_UNIT
    reasoning_cost = _money(reasoning_tokens) * price.reasoning_price / TOKENS_PER_PRICE_UNIT
    return input_cost, output_cost, reasoning_cost


def estimate_cost_usd(
    *,
    input_tokens: int,
    output_tokens: int,
    reasoning_tokens: int,
    provider: str,
    model: str,
    catalog: PricingCatalog,
) -> str:
    """Costo in dollari di un run, come stringa ``Decimal``, dai token cumulativi e dal listino.

    Stima a granularità di run: usa il prezzo del modello che ha risposto sui token totali
    consumati. Un modello fuori listino (o locale, prezzo zero) contribuisce 0. Restituisce una
    stringa perché il denaro è ``Decimal``, mai ``float`` (il ledger non deve accumulare errore).
    """
    price = catalog.resolve(provider, model)
    if price is None:
        return "0"
    input_cost, output_cost, reasoning_cost = compute_costs(
        input_tokens=max(0, input_tokens),
        cached_input_tokens=0,
        output_tokens=max(0, output_tokens),
        reasoning_tokens=max(0, reasoning_tokens),
        price=price,
    )
    return str(input_cost + output_cost + reasoning_cost)


def _int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def extract_token_counts(usage_metadata: dict[str, Any] | None) -> dict[str, int]:
    """Normalizza il ``usage_metadata`` LangChain nei quattro conteggi canonici.

    LangChain espone ``input_token_details.cache_read`` e
    ``output_token_details.reasoning`` quando il provider li fornisce; li leggiamo se
    presenti, altrimenti restano zero.
    """
    usage_metadata = usage_metadata or {}
    input_details = usage_metadata.get("input_token_details") or {}
    output_details = usage_metadata.get("output_token_details") or {}
    return {
        "input_tokens": _int(usage_metadata.get("input_tokens")),
        "cached_input_tokens": _int(input_details.get("cache_read")),
        "output_tokens": _int(usage_metadata.get("output_tokens")),
        "reasoning_tokens": _int(output_details.get("reasoning")),
    }


def build_call_usage(
    *,
    provider: str,
    model: str,
    execution_kind: ExecutionKind,
    usage_metadata: dict[str, Any] | None,
    catalog: PricingCatalog,
    when: str | None = None,
    effective_local_cost: Decimal | None = None,
) -> ModelCallUsage:
    """Costruisce un ``ModelCallUsage`` da un usage provider e dal listino versionato.

    Se il provider non ha riportato usage (``usage_metadata`` vuoto) l'esito è marcato
    ``usage_source='absent'`` e i costi restano zero: mentire con una stima non
    dichiarata è peggio di ammettere che il dato manca.
    """
    counts = extract_token_counts(usage_metadata)
    has_usage = any(counts.values())
    price = catalog.resolve(provider, model, when=when)
    if price is None or not has_usage:
        return ModelCallUsage(
            provider=provider,
            model=model,
            execution_kind=execution_kind,
            input_tokens=counts["input_tokens"],
            cached_input_tokens=counts["cached_input_tokens"],
            output_tokens=counts["output_tokens"],
            reasoning_tokens=counts["reasoning_tokens"],
            usage_source="provider" if has_usage else "absent",
            effective_local_cost=effective_local_cost,
        )
    input_cost, output_cost, reasoning_cost = compute_costs(price=price, **counts)
    return ModelCallUsage(
        provider=provider,
        model=model,
        execution_kind=execution_kind,
        input_tokens=counts["input_tokens"],
        cached_input_tokens=counts["cached_input_tokens"],
        output_tokens=counts["output_tokens"],
        reasoning_tokens=counts["reasoning_tokens"],
        input_cost=input_cost,
        output_cost=output_cost,
        reasoning_cost=reasoning_cost,
        effective_local_cost=effective_local_cost,
        currency=price.currency,
        pricing_version=price.version,
        usage_source="provider",
    )


@dataclass(frozen=True)
class RunUsageSummary:
    """Aggregato per run con le tre grandezze token tenute distinte.

    ``context_input_tokens`` è l'input dell'ULTIMA chiamata (dimensione del contesto a
    fine run), ``cumulative_input_tokens`` è la somma di tutte le chiamate (quanto è
    stato letto in totale). Confonderle è esattamente il bug che la Fase 0 elimina.
    """

    calls: int = 0
    context_input_tokens: int = 0
    cumulative_input_tokens: int = 0
    cumulative_output_tokens: int = 0
    reasoning_tokens: int = 0
    cached_input_tokens: int = 0
    billable_tokens: int = 0
    total_cost: Decimal = Decimal(0)
    effective_local_cost: Decimal = Decimal(0)
    currency: str = "USD"
    by_provider: dict[str, Decimal] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "calls": self.calls,
            "context_input_tokens": self.context_input_tokens,
            "cumulative_input_tokens": self.cumulative_input_tokens,
            "cumulative_output_tokens": self.cumulative_output_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "cached_input_tokens": self.cached_input_tokens,
            "billable_tokens": self.billable_tokens,
            "total_cost": str(self.total_cost),
            "effective_local_cost": str(self.effective_local_cost),
            "currency": self.currency,
            "by_provider": {name: str(cost) for name, cost in self.by_provider.items()},
        }


def aggregate_run_usage(calls: list[ModelCallUsage]) -> RunUsageSummary:
    """Somma una sequenza di chiamate mantenendo separate le tre grandezze token."""
    if not calls:
        return RunUsageSummary()
    context_input = 0
    cumulative_input = 0
    cumulative_output = 0
    reasoning = 0
    cached = 0
    billable = 0
    total_cost = Decimal(0)
    local_cost = Decimal(0)
    by_provider: dict[str, Decimal] = {}
    for call in calls:
        context_input = call.input_tokens  # l'ultima vince: è la fotografia finale
        cumulative_input += call.input_tokens
        cumulative_output += call.output_tokens
        reasoning += call.reasoning_tokens
        cached += call.cached_input_tokens
        billable += call.billable_tokens
        total_cost += call.total_cost
        if call.effective_local_cost is not None:
            local_cost += call.effective_local_cost
        by_provider[call.provider] = by_provider.get(call.provider, Decimal(0)) + call.total_cost
    return RunUsageSummary(
        calls=len(calls),
        context_input_tokens=context_input,
        cumulative_input_tokens=cumulative_input,
        cumulative_output_tokens=cumulative_output,
        reasoning_tokens=reasoning,
        cached_input_tokens=cached,
        billable_tokens=billable,
        total_cost=total_cost,
        effective_local_cost=local_cost,
        currency=calls[-1].currency,
        by_provider=by_provider,
    )


def with_pricing_version(entry: PriceEntry, version: str) -> PriceEntry:
    """Copia il listino cambiando solo la versione: usato quando lo si ricarica da DB."""
    return replace(entry, version=version)


def catalog_from_settings(settings: Any, *, version: str = "config") -> PricingCatalog:
    """Semina il catalogo dai prezzi per gradino già in ``Settings``.

    I prezzi tier (low/mid/high) sono l'unica fonte oggi in produzione; questo builder
    li promuove a listino versionato senza cambiarne i valori, così la Fase 0 non altera
    il costo mostrato e il resto del sistema può migrare a ``PricingCatalog`` in modo
    incrementale.
    """
    # (provider, model, price_in, price_out) per ogni gradino di ogni provider cloud a listino.
    rows = [
        ("openai", settings.openai_model_low, settings.openai_price_in_low,
         settings.openai_price_out_low),
        ("openai", settings.openai_model_mid, settings.openai_price_in_mid,
         settings.openai_price_out_mid),
        ("openai", settings.openai_model_high, settings.openai_price_in_high,
         settings.openai_price_out_high),
        ("anthropic", settings.anthropic_model_low, settings.anthropic_price_in_low,
         settings.anthropic_price_out_low),
        ("anthropic", settings.anthropic_model_mid, settings.anthropic_price_in_mid,
         settings.anthropic_price_out_mid),
        ("anthropic", settings.anthropic_model_high, settings.anthropic_price_in_high,
         settings.anthropic_price_out_high),
    ]
    seen: set[tuple[str, str]] = set()
    entries: list[PriceEntry] = []
    for provider, model, price_in, price_out in rows:
        key = (provider, model)
        if key in seen:
            continue
        seen.add(key)
        entries.append(
            PriceEntry(
                provider=provider,
                model=model,
                input_price=_money(price_in),
                output_price=_money(price_out),
                source="settings",
                version=version,
            )
        )
    return PricingCatalog(entries)
