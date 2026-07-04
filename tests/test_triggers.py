from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent_harness.config import Settings
from agent_harness.control_store import ControlStore
from agent_harness.triggers import TriggerScheduler, cron_matches


def _dt(minute: int = 0, hour: int = 0, day: int = 1, month: int = 1) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=UTC)


def make_store(tmp_path: Path) -> ControlStore:
    (tmp_path / "skills").mkdir()
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
