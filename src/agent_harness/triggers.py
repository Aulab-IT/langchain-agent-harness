from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from agent_harness.control_store import ControlStore

_LOGGER = logging.getLogger(__name__)

FireCallback = Callable[..., Awaitable[Any]]


def _match_field(field: str, value: int, low: int, high: int) -> bool:
    """Valuta un singolo campo cron (5 campi standard) contro un valore intero."""
    for part in field.split(","):
        part = part.strip()
        if part in ("*", "?"):
            return True
        step = 1
        base = part
        if "/" in part:
            base, _, step_str = part.partition("/")
            step = int(step_str)
        if base in ("*", "?", ""):
            start, end = low, high
        elif "-" in base:
            start_str, _, end_str = base.partition("-")
            start, end = int(start_str), int(end_str)
        else:
            start = end = int(base)
        if start < low or end > high or start > end:
            continue
        if value < start or value > end:
            continue
        if (value - start) % step == 0:
            return True
    return False


def cron_matches(expr: str, moment: datetime) -> bool:
    """Vero se l'espressione cron a 5 campi (min ora giorno mese giorno-settimana) copre `moment`.

    Domenica = 0 (o 7). Granularità al minuto: pensata per uno scheduler che valuta ogni tick.
    """
    fields = expr.split()
    if len(fields) != 5:
        raise ValueError("Cron non valido: servono 5 campi (min ora giorno mese giorno-settimana).")
    minute, hour, dom, month, dow = fields
    weekday = moment.isoweekday() % 7  # lunedì=1..sabato=6, domenica=0
    dow_ok = _match_field(dow, weekday, 0, 6) or _match_field(
        dow, 7 if weekday == 0 else weekday, 0, 7
    )
    return (
        _match_field(minute, moment.minute, 0, 59)
        and _match_field(hour, moment.hour, 0, 23)
        and _match_field(dom, moment.day, 1, 31)
        and _match_field(month, moment.month, 1, 12)
        and dow_ok
    )


class TriggerScheduler:
    """Task asincrono che valuta i trigger cron a ogni tick e ne avvia i run."""

    def __init__(
        self,
        store: ControlStore,
        on_fire: FireCallback,
        *,
        tick_seconds: int = 30,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.store = store
        self.on_fire = on_fire
        self.tick_seconds = tick_seconds
        self.clock = clock or (lambda: datetime.now(UTC))
        self._task: asyncio.Task[None] | None = None
        self._fired_minutes: dict[str, str] = {}

    async def tick(self) -> list[str]:
        """Valuta una volta i trigger cron. Ritorna gli id che hanno fatto fire (per i test)."""
        moment = self.clock()
        minute_key = moment.strftime("%Y-%m-%dT%H:%M")
        fired: list[str] = []
        for trigger in self.store.enabled_cron_triggers():
            expr = trigger.get("cron_expr") or ""
            try:
                if not cron_matches(expr, moment):
                    continue
            except ValueError:
                _LOGGER.warning("Trigger %s ha cron non valido: %r", trigger["id"], expr)
                continue
            if self._fired_minutes.get(trigger["id"]) == minute_key:
                continue
            self._fired_minutes[trigger["id"]] = minute_key
            try:
                await self.on_fire(trigger)
                fired.append(trigger["id"])
            except Exception:
                _LOGGER.exception("Fire trigger %s fallito", trigger["id"])
        return fired

    async def _loop(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception:
                _LOGGER.exception("Tick scheduler fallito")
            await asyncio.sleep(self.tick_seconds)

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop(), name="trigger-scheduler")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
