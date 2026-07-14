"""Budget hard provider-neutral per singolo run.

Il tracker è condiviso da root, router, grader e subagent. Prenota costo/token prima di una
chiamata per evitare che call parallele superino insieme il residuo, poi riconcilia la prenota
con usage reale del provider. Dopo un superamento nessuna nuova chiamata modello è ammessa.
"""

from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import asdict, dataclass
from decimal import Decimal
from math import ceil
from typing import Any

from langchain.agents.middleware import ModelRequest, ModelResponse, wrap_model_call
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage

from agent_harness.model_errors import invoke_with_model_retry
from agent_harness.usage import token_estimate

EventSink = Callable[[dict[str, Any]], None]
_MILLION = Decimal(1_000_000)


class BudgetExceededError(RuntimeError):
    """Run fermato perché una dimensione del budget è esaurita."""

    def __init__(self, dimension: str, message: str) -> None:
        super().__init__(message)
        self.dimension = dimension


class SubagentProgressState:
    """Segnali affidabili prodotti dai tool, condivisi col middleware del modello."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._outcomes: dict[str, int] = {}

    def record(self, outcomes: Sequence[str]) -> None:
        with self._lock:
            for outcome in outcomes:
                self._outcomes[outcome] = self._outcomes.get(outcome, 0) + 1

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return dict(self._outcomes)


@dataclass(frozen=True)
class BudgetRate:
    provider: str
    model: str
    tier: str | None = None
    input_per_million: Decimal = Decimal(0)
    output_per_million: Decimal = Decimal(0)

    @classmethod
    def from_values(
        cls,
        provider: str,
        model: str,
        input_per_million: float | str,
        output_per_million: float | str,
        tier: str | None = None,
    ) -> BudgetRate:
        return cls(
            provider=provider,
            model=model,
            tier=tier,
            input_per_million=Decimal(str(input_per_million)),
            output_per_million=Decimal(str(output_per_million)),
        )

    def cost(self, input_tokens: int, output_tokens: int) -> Decimal:
        return (
            Decimal(max(0, input_tokens)) * self.input_per_million
            + Decimal(max(0, output_tokens)) * self.output_per_million
        ) / _MILLION


@dataclass(frozen=True)
class RunBudgetLimits:
    max_tokens: int
    max_cost_usd: Decimal
    max_seconds: int
    max_model_calls: int
    max_subagent_calls: int
    max_subagent_model_calls: int
    max_subagent_tokens: int
    reserved_output_tokens: int
    warning_ratio: float = 0.7

    @classmethod
    def from_settings(cls, settings: Any) -> RunBudgetLimits:
        return cls(
            max_tokens=int(settings.harness_max_run_tokens),
            max_cost_usd=Decimal(str(settings.harness_max_run_cost_usd)),
            max_seconds=int(settings.harness_max_run_seconds),
            max_model_calls=int(settings.harness_max_model_calls),
            max_subagent_calls=int(settings.harness_max_subagent_calls),
            max_subagent_model_calls=int(settings.harness_max_subagent_model_calls),
            max_subagent_tokens=int(settings.harness_max_subagent_tokens),
            reserved_output_tokens=int(settings.harness_reserved_output_tokens),
            warning_ratio=float(settings.harness_budget_warning_ratio),
        )


@dataclass(frozen=True)
class BudgetReservation:
    id: str
    kind: str
    rate: BudgetRate
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal


@dataclass(frozen=True)
class RunBudgetSnapshot:
    cumulative_input_tokens: int
    cumulative_output_tokens: int
    total_tokens: int
    cost_usd: str
    model_calls: int
    subagent_calls: int
    by_call_kind: dict[str, dict[str, int]]
    elapsed_seconds: float
    token_ratio: float
    cost_ratio: float
    model_call_ratio: float
    subagent_call_ratio: float
    exceeded: bool
    exceeded_dimension: str
    exceeded_reason: str
    limits: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _message_text(message: BaseMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    return " ".join(
        str(block.get("text", ""))
        for block in content
        if isinstance(block, dict) and block.get("type") == "text"
    )


def estimate_request_tokens(request: ModelRequest) -> int:
    total = sum(token_estimate(_message_text(message)) for message in request.messages)
    system = request.system_message
    if system is not None:
        total += token_estimate(_message_text(system))
    # Gli schemi tool sono parte dell'input fatturato. Una rappresentazione compatta basta al
    # pre-check; il valore reale del provider sostituisce questa stima a chiamata conclusa.
    for tool in request.tools:
        total += token_estimate(
            {
                "name": getattr(tool, "name", ""),
                "description": getattr(tool, "description", ""),
                "args": getattr(tool, "args", {}),
            }
        )
    return max(1, total)


def response_usage(
    messages: Sequence[BaseMessage],
    *,
    estimated_input_tokens: int,
) -> tuple[int, int, int, bool]:
    input_tokens = 0
    output_tokens = 0
    reasoning_tokens = 0
    provider_usage = False
    for message in messages:
        if not isinstance(message, AIMessage):
            continue
        metadata: dict[str, Any] = dict(message.usage_metadata or {})
        if metadata:
            provider_usage = True
            input_tokens += int(metadata.get("input_tokens", 0) or 0)
            output_tokens += int(metadata.get("output_tokens", 0) or 0)
            details = metadata.get("output_token_details") or {}
            reasoning_tokens += int(details.get("reasoning", 0) or 0)
        elif not provider_usage:
            output_tokens += token_estimate(message.text)
    if input_tokens <= 0:
        input_tokens = estimated_input_tokens
    return input_tokens, output_tokens, reasoning_tokens, provider_usage


class RunBudgetTracker:
    """Ledger concorrente e hard-stop per costo operativo del run."""

    def __init__(self, limits: RunBudgetLimits, event_callback: EventSink | None = None) -> None:
        self.limits = limits
        self._emit = event_callback
        self._started = time.monotonic()
        self._lock = threading.RLock()
        self._input_tokens = 0
        self._output_tokens = 0
        self._cost_usd = Decimal(0)
        self._model_calls = 0
        self._subagent_calls = 0
        self._subagent_invocations: set[str] = set()
        self._kind_input_tokens: dict[str, int] = {}
        self._kind_output_tokens: dict[str, int] = {}
        self._kind_model_calls: dict[str, int] = {}
        self._reservations: dict[str, BudgetReservation] = {}
        self._reserved_tokens = 0
        self._reserved_cost = Decimal(0)
        configured_warning = min(0.95, max(0.1, limits.warning_ratio))
        later_thresholds = [
            ratio for ratio in (0.85, 0.95) if ratio > configured_warning
        ]
        self._warning_thresholds = tuple(
            sorted({configured_warning, *later_thresholds})
        )
        self._warnings_emitted: set[float] = set()
        self._exceeded_dimension = ""
        self._exceeded_reason = ""

    def _elapsed(self) -> float:
        return max(0.0, time.monotonic() - self._started)

    def _ratio(self, value: int | Decimal, maximum: int | Decimal) -> float:
        if maximum <= 0:
            return 0.0
        return round(float(value / maximum), 4)

    def _limits_dict(self) -> dict[str, Any]:
        return {
            "max_tokens": self.limits.max_tokens,
            "max_cost_usd": str(self.limits.max_cost_usd),
            "max_seconds": self.limits.max_seconds,
            "max_model_calls": self.limits.max_model_calls,
            "max_subagent_calls": self.limits.max_subagent_calls,
            "max_subagent_model_calls": self.limits.max_subagent_model_calls,
            "max_subagent_tokens": self.limits.max_subagent_tokens,
        }

    def snapshot(self) -> RunBudgetSnapshot:
        with self._lock:
            total = self._input_tokens + self._output_tokens
            return RunBudgetSnapshot(
                cumulative_input_tokens=self._input_tokens,
                cumulative_output_tokens=self._output_tokens,
                total_tokens=total,
                cost_usd=str(self._cost_usd),
                model_calls=self._model_calls,
                subagent_calls=self._subagent_calls,
                by_call_kind={
                    kind: {
                        "input_tokens": self._kind_input_tokens.get(kind, 0),
                        "output_tokens": self._kind_output_tokens.get(kind, 0),
                        "total_tokens": self._kind_input_tokens.get(kind, 0)
                        + self._kind_output_tokens.get(kind, 0),
                        "model_calls": calls,
                    }
                    for kind, calls in self._kind_model_calls.items()
                },
                elapsed_seconds=round(self._elapsed(), 3),
                token_ratio=self._ratio(total, self.limits.max_tokens),
                cost_ratio=self._ratio(self._cost_usd, self.limits.max_cost_usd),
                model_call_ratio=self._ratio(
                    self._model_calls, self.limits.max_model_calls
                ),
                subagent_call_ratio=self._ratio(
                    self._subagent_calls, self.limits.max_subagent_calls
                ),
                exceeded=bool(self._exceeded_reason),
                exceeded_dimension=self._exceeded_dimension,
                exceeded_reason=self._exceeded_reason,
                limits=self._limits_dict(),
            )

    def _event(self, event: dict[str, Any]) -> None:
        if self._emit is not None:
            self._emit(event)

    def _raise(self, dimension: str, reason: str, **details: Any) -> None:
        if not self._exceeded_reason:
            self._exceeded_dimension = dimension
            self._exceeded_reason = reason
            self._event(
                {
                    "type": "budget.exceeded",
                    "dimension": dimension,
                    "reason": reason,
                    **details,
                    **self.snapshot().to_dict(),
                }
            )
        raise BudgetExceededError(self._exceeded_dimension, self._exceeded_reason)

    def _check_time(self) -> None:
        if self._elapsed() >= self.limits.max_seconds:
            self._raise(
                "duration",
                f"Durata massima run raggiunta ({self.limits.max_seconds}s).",
            )

    def _maybe_warning(self, projected_tokens: int, projected_cost: Decimal) -> None:
        ratios = (
            self._ratio(projected_tokens, self.limits.max_tokens),
            self._ratio(projected_cost, self.limits.max_cost_usd),
            self._ratio(self._model_calls, self.limits.max_model_calls),
            self._ratio(self._subagent_calls, self.limits.max_subagent_calls),
        )
        pressure = max(ratios)
        for threshold in self._warning_thresholds:
            if threshold in self._warnings_emitted or pressure < threshold:
                continue
            self._warnings_emitted.add(threshold)
            self._event(
                {
                    "type": "budget.warning",
                    "level_percent": round(threshold * 100),
                    "projected_tokens": projected_tokens,
                    "projected_cost_usd": str(projected_cost),
                    **self.snapshot().to_dict(),
                }
            )

    def before_model_call(
        self,
        *,
        kind: str,
        rate: BudgetRate,
        estimated_input_tokens: int,
        reserved_output_tokens: int | None = None,
    ) -> BudgetReservation:
        with self._lock:
            if self._exceeded_reason:
                self._raise(self._exceeded_dimension, self._exceeded_reason)
            self._check_time()
            if self._model_calls >= self.limits.max_model_calls:
                self._raise(
                    "model_calls",
                    f"Massimo chiamate modello raggiunto ({self.limits.max_model_calls}).",
                )
            output_reserve = min(
                max(0, reserved_output_tokens or self.limits.reserved_output_tokens),
                self.limits.reserved_output_tokens,
            )
            input_estimate = max(1, estimated_input_tokens)
            reserved_tokens = input_estimate + output_reserve
            reserved_cost = rate.cost(input_estimate, output_reserve)
            projected_tokens = (
                self._input_tokens
                + self._output_tokens
                + self._reserved_tokens
                + reserved_tokens
            )
            projected_cost = self._cost_usd + self._reserved_cost + reserved_cost
            if projected_tokens > self.limits.max_tokens:
                self._raise(
                    "tokens",
                    "Prossima chiamata supererebbe il budget token "
                    f"({projected_tokens}/{self.limits.max_tokens}).",
                    current_total_tokens=self._input_tokens + self._output_tokens,
                    requested_input_tokens=input_estimate,
                    reserved_output_tokens=output_reserve,
                    projected_tokens=projected_tokens,
                )
            if projected_cost > self.limits.max_cost_usd:
                self._raise(
                    "cost",
                    "Prossima chiamata supererebbe il budget costo "
                    f"(${projected_cost}/${self.limits.max_cost_usd}).",
                    projected_cost_usd=str(projected_cost),
                )
            if kind.startswith("subagent:"):
                kind_calls = self._kind_model_calls.get(kind, 0)
                if kind_calls >= self.limits.max_subagent_model_calls:
                    self._raise(
                        "subagent_model_calls",
                        f"Massimo chiamate modello per {kind} raggiunto "
                        f"({self.limits.max_subagent_model_calls}).",
                        call_kind=kind,
                    )
                kind_reserved = sum(
                    item.input_tokens + item.output_tokens
                    for item in self._reservations.values()
                    if item.kind == kind
                )
                kind_total = (
                    self._kind_input_tokens.get(kind, 0)
                    + self._kind_output_tokens.get(kind, 0)
                    + kind_reserved
                    + reserved_tokens
                )
                if kind_total > self.limits.max_subagent_tokens:
                    self._raise(
                        "subagent_tokens",
                        f"Prossima chiamata supererebbe il budget token di {kind} "
                        f"({kind_total}/{self.limits.max_subagent_tokens}).",
                        call_kind=kind,
                        projected_tokens=kind_total,
                    )
            reservation = BudgetReservation(
                id=str(uuid.uuid4()),
                kind=kind,
                rate=rate,
                input_tokens=input_estimate,
                output_tokens=output_reserve,
                cost_usd=reserved_cost,
            )
            self._model_calls += 1
            self._kind_model_calls[kind] = self._kind_model_calls.get(kind, 0) + 1
            self._reserved_tokens += reserved_tokens
            self._reserved_cost += reserved_cost
            self._reservations[reservation.id] = reservation
            self._maybe_warning(projected_tokens, projected_cost)
            return reservation

    def cancel_model_call(self, reservation: BudgetReservation) -> None:
        with self._lock:
            current = self._reservations.pop(reservation.id, None)
            if current is None:
                return
            self._reserved_tokens -= current.input_tokens + current.output_tokens
            self._reserved_cost -= current.cost_usd

    def record_retry_estimate(self, reservation: BudgetReservation) -> None:
        """Conta conservativamente l'input di un tentativo provider fallito durante stream."""
        with self._lock:
            current = self._reservations.get(reservation.id)
            if current is None:
                return
            retry_cost = current.rate.cost(current.input_tokens, 0)
            projected_tokens = (
                self._input_tokens
                + self._output_tokens
                + self._reserved_tokens
                + current.input_tokens
            )
            projected_cost = self._cost_usd + self._reserved_cost + retry_cost
            if projected_tokens > self.limits.max_tokens:
                self._raise(
                    "tokens",
                    "Retry provider supererebbe il budget token "
                    f"({projected_tokens}/{self.limits.max_tokens}).",
                )
            if projected_cost > self.limits.max_cost_usd:
                self._raise(
                    "cost",
                    "Retry provider supererebbe il budget costo "
                    f"(${projected_cost}/${self.limits.max_cost_usd}).",
                )
            if current.kind.startswith("subagent:"):
                kind_total = (
                    self._kind_input_tokens.get(current.kind, 0)
                    + self._kind_output_tokens.get(current.kind, 0)
                    + sum(
                        item.input_tokens + item.output_tokens
                        for item in self._reservations.values()
                        if item.kind == current.kind
                    )
                    + current.input_tokens
                )
                if kind_total > self.limits.max_subagent_tokens:
                    self._raise(
                        "subagent_tokens",
                        f"Retry provider supererebbe il budget token di {current.kind} "
                        f"({kind_total}/{self.limits.max_subagent_tokens}).",
                    )
            self._input_tokens += current.input_tokens
            self._kind_input_tokens[current.kind] = (
                self._kind_input_tokens.get(current.kind, 0) + current.input_tokens
            )
            self._cost_usd += retry_cost
            self._event(
                {
                    "type": "budget.retry_estimated",
                    "call_kind": current.kind,
                    "provider": current.rate.provider,
                    "model": current.rate.model,
                    "estimated_failed_input_tokens": current.input_tokens,
                    "estimated_failed_cost_usd": str(retry_cost),
                    **self.snapshot().to_dict(),
                }
            )

    def complete_model_call(
        self,
        reservation: BudgetReservation,
        messages: Sequence[BaseMessage],
    ) -> RunBudgetSnapshot:
        input_tokens, output_tokens, reasoning_tokens, provider_usage = response_usage(
            messages,
            estimated_input_tokens=reservation.input_tokens,
        )
        with self._lock:
            current = self._reservations.pop(reservation.id, None)
            if current is None:
                return self.snapshot()
            self._reserved_tokens -= current.input_tokens + current.output_tokens
            self._reserved_cost -= current.cost_usd
            self._input_tokens += input_tokens
            self._output_tokens += output_tokens
            self._kind_input_tokens[reservation.kind] = (
                self._kind_input_tokens.get(reservation.kind, 0) + input_tokens
            )
            self._kind_output_tokens[reservation.kind] = (
                self._kind_output_tokens.get(reservation.kind, 0) + output_tokens
            )
            self._cost_usd += reservation.rate.cost(input_tokens, output_tokens)
            snapshot = self.snapshot()
            self._event(
                {
                    "type": "budget.updated",
                    "call_kind": reservation.kind,
                    "provider": reservation.rate.provider,
                    "model": reservation.rate.model,
                    "usage_source": "provider" if provider_usage else "estimated",
                    "call_id": reservation.id,
                    "tier": reservation.rate.tier,
                    "call_input_tokens": input_tokens,
                    "call_output_tokens": output_tokens,
                    "call_reasoning_tokens": reasoning_tokens,
                    "call_input_cost_usd": str(
                        reservation.rate.cost(input_tokens, 0)
                    ),
                    "call_output_cost_usd": str(
                        reservation.rate.cost(0, output_tokens)
                    ),
                    **snapshot.to_dict(),
                }
            )
            if snapshot.total_tokens > self.limits.max_tokens:
                self._raise(
                    "tokens",
                    f"Budget token superato ({snapshot.total_tokens}/{self.limits.max_tokens}).",
                )
            if Decimal(snapshot.cost_usd) > self.limits.max_cost_usd:
                self._raise(
                    "cost",
                    f"Budget costo superato (${snapshot.cost_usd}/${self.limits.max_cost_usd}).",
                )
            return snapshot

    def record_estimated_call(
        self,
        reservation: BudgetReservation,
        output: Any,
    ) -> RunBudgetSnapshot:
        message = AIMessage(content=str(output))
        return self.complete_model_call(reservation, [message])

    def start_subagent_call(
        self, subagent_name: str, invocation_id: str | None = None
    ) -> bool:
        with self._lock:
            if invocation_id and invocation_id in self._subagent_invocations:
                return False
            if self._exceeded_reason:
                self._raise(self._exceeded_dimension, self._exceeded_reason)
            self._check_time()
            if self._subagent_calls >= self.limits.max_subagent_calls:
                self._raise(
                    "subagent_calls",
                    "Massimo chiamate subagent raggiunto "
                    f"({self.limits.max_subagent_calls}).",
                )
            remaining_tokens = self.limits.max_tokens - (
                self._input_tokens + self._output_tokens + self._reserved_tokens
            )
            minimum_start = min(
                self.limits.max_tokens,
                max(10_000, self.limits.reserved_output_tokens * 2),
            )
            if remaining_tokens < minimum_start:
                self._raise(
                    "subagent_budget",
                    f"Budget residuo insufficiente per avviare {subagent_name} "
                    f"({remaining_tokens} token disponibili; minimo {minimum_start}).",
                    subagent=subagent_name,
                    remaining_tokens=remaining_tokens,
                    minimum_start_tokens=minimum_start,
                )
            self._subagent_calls += 1
            if invocation_id:
                self._subagent_invocations.add(invocation_id)
            self._maybe_warning(
                self._input_tokens + self._output_tokens + self._reserved_tokens,
                self._cost_usd + self._reserved_cost,
            )
            return True

    def exceed(self, dimension: str, reason: str) -> None:
        """Registra uno stop esterno (per esempio il timeout dell'intero coroutine run)."""
        with self._lock:
            self._raise(dimension, reason)


def build_fixed_model_budget_middleware(
    tracker: RunBudgetTracker,
    rate: BudgetRate,
    *,
    kind: str,
    progress: SubagentProgressState | None = None,
    event_callback: EventSink | None = None,
) -> Any:
    """Budget subagent con pressione precoce e ultima call riservata alla consegna."""

    emitted: set[str] = set()

    def prepared_request(request: ModelRequest) -> ModelRequest:
        snapshot = tracker.snapshot()
        used_calls = int(snapshot.by_call_kind.get(kind, {}).get("model_calls", 0))
        maximum = tracker.limits.max_subagent_model_calls
        next_call = used_calls + 1
        threshold = max(1, ceil(maximum * 0.8))
        outcomes = progress.snapshot() if progress is not None else {}
        validation_signal = outcomes.get("validation_passed_with_warnings", 0) > 0
        dependency_signal = outcomes.get("dependency_missing", 0) > 0
        pressure = next_call >= threshold
        force_finalize = next_call >= maximum
        if not (pressure or validation_signal or dependency_signal):
            return request

        guidance = [
            "## Harness completion policy",
            f"Subagent model calls: next {next_call}/{maximum}.",
        ]
        if validation_signal:
            guidance.append(
                "A validator reported pass-with-warnings and zero errors. Treat this as a "
                "successful check unless a warning directly violates an explicit success criterion."
            )
        if dependency_signal:
            guidance.append(
                "A dependency or runtime is missing. Do not probe it repeatedly. If it is optional "
                "or duplicates a passed check, report the limitation and complete. If mandatory, "
                "request one approved installation or report BLOCKED."
            )
        if pressure:
            guidance.append(
                "Finalization mode: stop optional exploration and duplicate verification. Complete "
                "only mandatory unmet criteria, then return TASK_STATUS and concrete EVIDENCE."
            )
        if force_finalize:
            guidance.append(
                "This is the reserved final response call. No tools are available. Return the "
                "completion contract now, preserving any verified artifact or partial result."
            )

        base = request.system_message.text if request.system_message is not None else ""
        updated = request.override(
            system_message=SystemMessage(content=f"{base}\n\n" + "\n".join(guidance))
        )
        if force_finalize:
            updated = updated.override(tools=[], tool_choice=None)

        mode = "forced" if force_finalize else "started"
        reason = "pressure" if pressure else "tool_outcome"
        event_key = f"{mode}:{reason}"
        if event_callback is not None and event_key not in emitted:
            emitted.add(event_key)
            event_callback(
                {
                    "type": f"subagent.finalization.{mode}",
                    "call_kind": kind,
                    "used_model_calls": used_calls,
                    "next_model_call": next_call,
                    "max_model_calls": maximum,
                    "validation_passed_with_warnings": validation_signal,
                    "dependency_missing": dependency_signal,
                    "tools_disabled": force_finalize,
                }
            )
        return updated

    @wrap_model_call
    async def enforce(
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        request = prepared_request(request)
        reservation = tracker.before_model_call(
            kind=kind,
            rate=rate,
            estimated_input_tokens=estimate_request_tokens(request),
        )
        try:
            response = await invoke_with_model_retry(
                lambda: handler(request),
                event_callback=event_callback,
                call_kind=kind,
                model=rate.model,
                on_retry=lambda _exc, _details: tracker.record_retry_estimate(reservation),
            )
        except Exception:
            tracker.cancel_model_call(reservation)
            raise
        tracker.complete_model_call(reservation, response.result)
        return response

    return enforce


__all__ = [
    "BudgetExceededError",
    "BudgetRate",
    "BudgetReservation",
    "RunBudgetLimits",
    "RunBudgetSnapshot",
    "RunBudgetTracker",
    "SubagentProgressState",
    "build_fixed_model_budget_middleware",
    "estimate_request_tokens",
    "response_usage",
]
