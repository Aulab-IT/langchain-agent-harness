from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent_harness.config import Settings
from agent_harness.control_store import ControlStore
from agent_harness.triggers import (
    TriggerScheduler,
    cron_matches,
    describe_cron,
    next_runs,
)


def _dt(minute: int = 0, hour: int = 0, day: int = 1, month: int = 1) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=UTC)


def make_store(tmp_path: Path) -> ControlStore:
    (tmp_path / ".agents" / "skills").mkdir(parents=True)
    (tmp_path / "memories").mkdir()
    (tmp_path / "memories" / "AGENTS.md").write_text("# Memory\n")
    return ControlStore(Settings(_env_file=None, project_root=tmp_path))


def test_cron_wildcard_always_matches() -> None:
    assert cron_matches("* * * * *", _dt())


def test_cron_specific_minute_and_hour() -> None:
    assert cron_matches("30 14 * * *", _dt(30, 14))
    assert not cron_matches("30 14 * * *", _dt(31, 14))


def test_cron_step_and_list() -> None:
    assert cron_matches("*/15 * * * *", _dt(45))
    assert not cron_matches("*/15 * * * *", _dt(7))
    assert cron_matches("0,30 * * * *", _dt(30))


def test_cron_weekday_range() -> None:
    moment = datetime(2026, 7, 3, 9, 0, tzinfo=UTC)
    weekday = moment.isoweekday() % 7
    assert cron_matches(f"0 9 * * {weekday}", moment)
    assert not cron_matches(f"0 9 * * {(weekday + 1) % 7}", moment)


def test_nine_in_rome_is_not_nine_in_utc() -> None:
    """Il bug che rendeva inutile qualunque selettore: `0 9 * * *` valutato in UTC."""
    winter = datetime(2026, 1, 15, 8, 0, tzinfo=UTC)  # 09:00 a Roma (CET, UTC+1)
    summer = datetime(2026, 7, 15, 7, 0, tzinfo=UTC)  # 09:00 a Roma (CEST, UTC+2)

    assert cron_matches("0 9 * * *", winter, "Europe/Rome")
    assert cron_matches("0 9 * * *", summer, "Europe/Rome")
    # Lo stesso istante in UTC non è le nove.
    assert not cron_matches("0 9 * * *", winter, "UTC")
    assert not cron_matches("0 9 * * *", summer, "UTC")


def test_daylight_saving_is_handled_by_the_zone_not_by_cron() -> None:
    """A luglio Roma è UTC+2: le 09:00 locali cadono alle 07:00 UTC, non alle 08:00."""
    assert not cron_matches("0 9 * * *", datetime(2026, 7, 15, 8, 0, tzinfo=UTC), "Europe/Rome")


def test_unknown_timezone_is_rejected_not_silently_treated_as_utc() -> None:
    with pytest.raises(ValueError, match="Timezone non valida"):
        cron_matches("0 9 * * *", datetime(2026, 1, 15, 8, 0, tzinfo=UTC), "Marte/Olympus")


def test_next_runs_are_returned_in_the_trigger_timezone() -> None:
    runs = next_runs("0 9 * * *", "Europe/Rome", count=3)

    assert len(runs) == 3
    assert all(moment.hour == 9 and moment.minute == 0 for moment in runs)
    assert runs[0] < runs[1] < runs[2]


def test_next_runs_is_short_rather_than_wrong_for_an_impossible_expression() -> None:
    assert next_runs("0 0 30 2 *", "UTC", count=3) == []


def test_describe_cron_reads_like_italian() -> None:
    assert describe_cron("0 9 * * *", "Europe/Rome") == "Ogni giorno alle 09:00 (fuso Europe/Rome)"
    assert describe_cron("*/15 * * * *") == "Ogni 15 minuti"
    assert describe_cron("30 8 * * 1") == "Ogni lunedì alle 08:30"
    assert describe_cron("0 0 1 * *") == "Il giorno 1 di ogni mese alle 00:00"
    # Forme che non sappiamo tradurre restano l'espressione, invece di una frase inventata.
    assert describe_cron("5,17 3-6 * * 2-4") == "5,17 3-6 * * 2-4"


def test_cron_invalid_raises() -> None:
    with pytest.raises(ValueError):
        cron_matches("* * * *", _dt())


@pytest.mark.asyncio
async def test_scheduler_fires_once_per_minute(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    trigger = store.create_trigger(
        kind="cron", name="orario", goal_template="fai", cron_expr="* * * * *"
    )
    fired: list[str] = []

    async def on_fire(item: dict[str, object]) -> None:
        fired.append(str(item["id"]))

    scheduler = TriggerScheduler(store, on_fire, clock=lambda: _dt(0, 9))
    await scheduler.tick()
    await scheduler.tick()  # stesso minuto: non deve rifire

    assert fired == [trigger["id"]]
    store.close()


@pytest.mark.asyncio
async def test_scheduler_skips_disabled_and_unmatched(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    store.create_trigger(kind="cron", name="mai", goal_template="x", cron_expr="0 3 * * *")
    disabled = store.create_trigger(
        kind="cron", name="off", goal_template="x", cron_expr="* * * * *"
    )
    store.set_trigger_enabled(disabled["id"], False)
    fired: list[str] = []

    async def on_fire(item: dict[str, object]) -> None:
        fired.append(str(item["id"]))

    scheduler = TriggerScheduler(store, on_fire, clock=lambda: _dt(0, 9))
    await scheduler.tick()

    assert fired == []
    store.close()


@pytest.mark.asyncio
async def test_durable_claim_prevents_double_fire_across_restart(tmp_path: Path) -> None:
    from agent_harness.durable import DurableStore, idempotency_key

    store = make_store(tmp_path)
    trigger = store.create_trigger(
        kind="cron", name="orario", goal_template="fai", cron_expr="* * * * *"
    )
    durable = DurableStore(tmp_path / "durable.sqlite")

    def claim(tid: str, minute: str) -> bool:
        return durable.claim_once(idempotency_key("trigger", tid, minute), kind="trigger_fire")

    fired: list[str] = []

    async def on_fire(item: dict[str, object]) -> None:
        fired.append(str(item["id"]))

    # Primo scheduler (prima del "riavvio"): scatta una volta.
    s1 = TriggerScheduler(store, on_fire, clock=lambda: _dt(0, 9), claim_fire=claim)
    await s1.tick()
    # Riavvio: un nuovo scheduler con cache in memoria vuota, stesso minuto. Senza claim
    # durevole rifire; con il claim durevole (stesso durable.sqlite) NON rifire.
    s2 = TriggerScheduler(store, on_fire, clock=lambda: _dt(0, 9), claim_fire=claim)
    await s2.tick()

    assert fired == [trigger["id"]]
    durable.close()
    store.close()
