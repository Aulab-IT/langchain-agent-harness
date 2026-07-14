from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import pytest

import agent_harness.cli as cli
from agent_harness.run_budget import BudgetExceededError


@pytest.mark.asyncio
async def test_execute_goal_renders_budget_stop_without_traceback(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    harness = SimpleNamespace()

    @asynccontextmanager
    async def fake_build_harness(*args: object, **kwargs: object) -> Any:
        del args, kwargs
        yield harness

    class FakeGoalRunner:
        def __init__(self, *args: object, **kwargs: object) -> None:
            del args, kwargs

        async def run(self, goal: str, *, thread_id: str) -> object:
            del goal, thread_id
            raise BudgetExceededError("cost", "Costo massimo raggiunto.")

    monkeypatch.setattr(cli, "build_harness", fake_build_harness)
    monkeypatch.setattr(cli, "GoalRunner", FakeGoalRunner)

    await cli.execute_goal("Obiettivo", "thread-test")

    output = capsys.readouterr().out
    assert "Run fermato per budget: Costo massimo raggiunto." in output
    assert "Traceback" not in output
