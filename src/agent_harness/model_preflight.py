"""Probe provider/modello eseguito prima che il run possa usare tool o deleghe."""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Callable, Iterable, Sequence
from typing import Any, cast

from langchain_core.messages import HumanMessage

from agent_harness.config import Settings
from agent_harness.factory import build_tier_models, tier_spec
from agent_harness.middleware import TIERS, Override, Tier

EventSink = Callable[[dict[str, Any]], None]


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
        required.update(cast(Tier, tier) for tier in subagent_tiers if tier in TIERS)
    return tuple(tier for tier in TIERS if tier in required)


async def preflight_tier_models(
    settings: Settings,
    tiers: Sequence[Tier],
    *,
    event_callback: EventSink | None = None,
) -> None:
    """Invoca una volta ogni coppia provider/modello richiesta, con cache TTL."""
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
        model = models[used_by[0]].model
        try:
            await asyncio.wait_for(
                model.ainvoke([HumanMessage(content="Runtime preflight. Reply with OK only.")]),
                timeout=settings.harness_model_preflight_timeout_seconds,
            )
        except Exception as exc:
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
        await asyncio.gather(*(probe(identity, used_by) for identity, used_by in pending))


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
