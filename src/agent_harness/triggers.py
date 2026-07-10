from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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


def resolve_timezone(name: str) -> ZoneInfo:
    """Un nome di timezone non valido non deve far girare un trigger all'ora sbagliata."""
    try:
        return ZoneInfo(name or "UTC")
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"Timezone non valida: {name}") from exc


def cron_matches(expr: str, moment: datetime, timezone: str = "UTC") -> bool:
    """Vero se l'espressione cron a 5 campi (min ora giorno mese giorno-settimana) copre `moment`.

    `moment` può essere in qualunque fuso: viene convertito in `timezone` prima del confronto,
    perché `0 9 * * *` significa «alle nove» nel fuso di chi ha creato il trigger, non alle nove
    UTC. Senza questa conversione, un trigger italiano scatta alle 10:00 d'inverno e alle 11:00
    d'estate. La conversione gestisce da sola l'ora legale, che il cron non conosce.

    Domenica = 0 (o 7). Granularità al minuto: pensata per uno scheduler che valuta ogni tick.
    """
    fields = expr.split()
    if len(fields) != 5:
        raise ValueError("Cron non valido: servono 5 campi (min ora giorno mese giorno-settimana).")
    moment = moment.astimezone(resolve_timezone(timezone))
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


_WEEKDAY_NAMES = ["domenica", "lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato"]


def next_runs(expr: str, timezone: str = "UTC", count: int = 3) -> list[datetime]:
    """Le prossime `count` esecuzioni, nel fuso del trigger.

    Scansione minuto per minuto su un anno: l'espressione ha granularità al minuto e non serve
    un risolutore analitico per mostrare tre date. Se in un anno non scatta mai (per esempio
    `0 0 30 2 *`, il 30 febbraio), la lista torna corta invece che vuota di significato.
    """
    zone = resolve_timezone(timezone)
    cursor = datetime.now(zone).replace(second=0, microsecond=0) + timedelta(minutes=1)
    horizon = cursor + timedelta(days=366)
    found: list[datetime] = []
    while cursor < horizon and len(found) < count:
        if cron_matches(expr, cursor, timezone):
            found.append(cursor)
        cursor += timedelta(minutes=1)
    return found


def _describe_field(field: str, singular: str) -> str:
    if field in ("*", "?"):
        return f"ogni {singular}"
    if field.startswith("*/"):
        return f"ogni {field[2:]} {singular}"
    return field


def describe_cron(expr: str, timezone: str = "UTC") -> str:
    """Rende leggibile un'espressione cron. Copre le forme comuni, non tutte."""
    fields = expr.split()
    if len(fields) != 5:
        return expr
    minute, hour, dom, month, dow = fields
    zone_suffix = f" (fuso {timezone})" if timezone and timezone != "UTC" else ""

    if minute.startswith("*/") and hour == "*":
        return f"Ogni {minute[2:]} minuti{zone_suffix}"
    if minute == "*" and hour == "*":
        return f"Ogni minuto{zone_suffix}"
    if hour == "*" and minute.isdigit():
        return f"Ogni ora, al minuto {int(minute)}{zone_suffix}"
    if minute.isdigit() and hour.isdigit():
        clock = f"{int(hour):02d}:{int(minute):02d}"
        if dow not in ("*", "?"):
            if dow.isdigit():
                return f"Ogni {_WEEKDAY_NAMES[int(dow) % 7]} alle {clock}{zone_suffix}"
            return f"Nei giorni {dow} alle {clock}{zone_suffix}"
        if dom not in ("*", "?"):
            return f"Il giorno {dom} di ogni mese alle {clock}{zone_suffix}"
        if month not in ("*", "?"):
            return f"Nel mese {month}, ogni giorno alle {clock}{zone_suffix}"
        return f"Ogni giorno alle {clock}{zone_suffix}"
    return expr


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
        # La chiave anti-doppio-fire è in UTC: indipendente dal fuso del singolo trigger, e
        # immune ai salti dell'ora legale, che nel fuso locale ripetono lo stesso minuto.
        minute_key = moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M")
        # Serve solo a non far scattare due volte lo stesso trigger nello stesso minuto: le
        # voci dei minuti passati non hanno più effetto e crescerebbero senza limite.
        self._fired_minutes = {
            trigger_id: key
            for trigger_id, key in self._fired_minutes.items()
            if key == minute_key
        }
        fired: list[str] = []
        for trigger in self.store.enabled_cron_triggers():
            expr = trigger.get("cron_expr") or ""
            timezone = trigger.get("timezone") or "UTC"
            try:
                if not cron_matches(expr, moment, timezone):
                    continue
            except ValueError:
                _LOGGER.warning(
                    "Trigger %s ha cron o timezone non validi: %r / %r",
                    trigger["id"],
                    expr,
                    timezone,
                )
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
