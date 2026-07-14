"""Probe provider/modello eseguito prima che il run possa usare tool o deleghe."""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Callable, Iterable, Sequence
from typing import Any

from langchain_core.messages import HumanMessage

from agent_harness.config import Settings
from agent_harness.factory import build_tier_models, tier_spec
from agent_harness.middleware import TIERS, Override, Tier
from agent_harness.run_budget import (
    BudgetExceededError,
    BudgetRate,
    RunBudgetTracker,
)
from agent_harness.usage import token_estimate

EventSink = Callable[[dict[str, Any]], None]
_PREFLIGHT_PROMPT = "Runtime preflight. Reply with OK only."
_PREFLIGHT_OUTPUT_RESERVE = 16


class ModelPreflightError(RuntimeError):
    """Configurazione modello non invocabile prima dell'avvio operativo del run."""


_SUCCESS_CACHE: dict[tuple[str, str], float] = {}
_CACHE_LOCK = threading.Lock()


def required_preflight_tiers(
    settings: Settings,
    *,
    model_override: Override = "auto",
    subagent_tiers: Iterable[str] = (),
) -> tuple[Tier, ...]:
    """Gradini potenzialmente usati da root, grader, escalation o roster del run."""
    required: set[Tier] = {"low"}
    if settings.harness_enable_rubric or settings.harness_max_continuations >= 2:
        required.add("mid")
    if settings.harness_max_continuations >= 3:
        required.add("high")
    if model_override in TIERS:
        required.add(model_override)
    if settings.harness_enable_subagent_routing:
        required.update(tier for tier in subagent_tiers if tier in TIERS)
    return tuple(tier for tier in TIERS if tier in required)


async def preflight_tier_models(
    settings: Settings,
    tiers: Sequence[Tier],
    *,
    event_callback: EventSink | None = None,
    budget_tracker: RunBudgetTracker | None = None,
) -> None:
    """Invoca una volta ogni coppia provider/modello richiesta, con cache TTL e budget.

    Il preflight e' parte del run: quando esegue davvero una chiamata deve prenotare e
    contabilizzare token/costo nello stesso tracker usato da root, router, grader e subagent.
    Una hit di cache non consuma budget perche' non invoca alcun provider.
    """
    models = build_tier_models(settings)
    grouped: dict[tuple[str, str], list[Tier]] = {}
    for tier in tiers:
        spec = tier_spec(settings, tier)
        grouped.setdefault((spec.provider, spec.name), []).append(tier)

    now = time.monotonic()
    ttl = settings.harness_model_preflight_ttl_seconds
    pending = []
    for identity, used_by in grouped.items():
        with _CACHE_LOCK:
            cached_at = _SUCCESS_CACHE.get(identity)
        if cached_at is not None and ttl > 0 and now - cached_at <= ttl:
            if event_callback is not None:
                event_callback(
                    {
                        "type": "model.preflight.completed",
                        "provider": identity[0],
                        "model": identity[1],
                        "tiers": used_by,
                        "cached": True,
                        "elapsed_ms": 0,
                    }
                )
            continue
        pending.append((identity, used_by))

    async def probe(identity: tuple[str, str], used_by: list[Tier]) -> None:
        provider, model_name = identity
        model = models[used_by[0]].model
        reservation = None
        tracker = budget_tracker
        if tracker is not None:
            spec = tier_spec(settings, used_by[0])
            reservation = tracker.before_model_call(
                kind=f"preflight:{provider}:{model_name}",
                rate=BudgetRate.from_values(
                    provider,
                    model_name,
                    spec.price_in,
                    spec.price_out,
                    tier=used_by[0],
                ),
                estimated_input_tokens=token_estimate(_PREFLIGHT_PROMPT),
                reserved_output_tokens=_PREFLIGHT_OUTPUT_RESERVE,
            )
        if event_callback is not None:
            event_callback(
                {
                    "type": "model.preflight.started",
                    "provider": provider,
                    "model": model_name,
                    "tiers": used_by,
                }
            )
        started = time.monotonic()
        try:
            response = await asyncio.wait_for(
                model.ainvoke([HumanMessage(content=_PREFLIGHT_PROMPT)]),
                timeout=settings.harness_model_preflight_timeout_seconds,
            )
            if reservation is not None and tracker is not None:
                tracker.complete_model_call(reservation, [response])
        except asyncio.CancelledError:
            if reservation is not None and tracker is not None:
                tracker.cancel_model_call(reservation)
            raise
        except BudgetExceededError:
            if reservation is not None and tracker is not None:
                tracker.cancel_model_call(reservation)
            raise
        except Exception as exc:
            if reservation is not None and tracker is not None:
                tracker.cancel_model_call(reservation)
            elapsed = round((time.monotonic() - started) * 1_000)
            if event_callback is not None:
                event_callback(
                    {
                        "type": "model.preflight.failed",
                        "provider": provider,
                        "model": model_name,
                        "tiers": used_by,
                        "elapsed_ms": elapsed,
                        "error": str(exc)[:500],
                    }
                )
            raise ModelPreflightError(
                f"Preflight fallito per {provider}/{model_name} "
                f"(gradini: {', '.join(used_by)}): {str(exc)[:300]}"
            ) from exc
        with _CACHE_LOCK:
            _SUCCESS_CACHE[identity] = time.monotonic()
        if event_callback is not None:
            event_callback(
                {
                    "type": "model.preflight.completed",
                    "provider": provider,
                    "model": model_name,
                    "tiers": used_by,
                    "cached": False,
                    "elapsed_ms": round((time.monotonic() - started) * 1_000),
                }
            )

    if pending:
        tasks = [
            asyncio.create_task(probe(identity, used_by)) for identity, used_by in pending
        ]
        try:
            await asyncio.gather(*tasks)
        except BaseException:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise


def clear_preflight_cache() -> None:
    """Helper esplicito per test e cambio credenziali a caldo."""
    with _CACHE_LOCK:
        _SUCCESS_CACHE.clear()


__all__ = [
    "ModelPreflightError",
    "clear_preflight_cache",
    "preflight_tier_models",
    "required_preflight_tiers",
]
