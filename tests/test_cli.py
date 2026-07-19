from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import pytest

import agent_harness.cli as cli
from agent_harness.command_review import build_approval_summary
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


# --- parità informativa fra CLI e Control Center --------------------------------------


def _network_payload() -> dict[str, Any]:
    return {
        "action_requests": [
            {
                "action": "docker_exec",
                "args": {"command": "curl https://example.com", "with_network": True},
            }
        ]
    }


def test_cli_approval_shows_the_same_static_review_as_the_web_ui() -> None:
    """La CLI mostrava il payload grezzo: chi approvava da terminale decideva con meno
    informazioni di chi approvava dal browser, sullo stesso gate di sicurezza."""
    summary = build_approval_summary(_network_payload())
    rendered = cli.render_approval(summary)
    assert "curl https://example.com" in rendered
    assert "Cosa fa" in rendered
    assert "Accesso rete temporaneo" in rendered


def test_cli_approval_surfaces_warnings() -> None:
    summary = build_approval_summary(
        {"action_requests": [{"action": "docker_exec", "args": {"command": "rm -rf /workspace"}}]}
    )
    rendered = cli.render_approval(summary)
    assert "Attenzione" in rendered


def test_cli_approval_renders_a_payload_without_command() -> None:
    rendered = cli.render_approval(build_approval_summary({"action_requests": [{}]}))
    assert "sandbox Docker" in rendered
    assert "Comando" not in rendered


@pytest.mark.asyncio
async def test_cli_approval_defaults_to_refusing_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    def fake_confirm(prompt: str, default: bool = True) -> bool:
        seen["prompt"] = prompt
        seen["default"] = default
        return default

    monkeypatch.setattr(cli.typer, "confirm", fake_confirm)
    assert await cli.ask_approval(_network_payload()) is False
    assert seen["default"] is False
    assert "rete" in seen["prompt"]
