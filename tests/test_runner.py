from types import SimpleNamespace
from typing import Any

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
from langgraph.types import Interrupt

from agent_harness.middleware import TierLadder
from agent_harness.runner import GoalRunner, final_text
from agent_harness.verification import GradeResult


class FakeGrader:
    def __init__(self, results: list[GradeResult]) -> None:
        self.results = list(results)
        self.calls: list[tuple[str, str]] = []

    async def grade(self, goal: str, answer: str) -> GradeResult:
        self.calls.append((goal, answer))
        return self.results.pop(0)


class FakeGraph:
    def __init__(self, outputs: list[dict[str, Any]]) -> None:
        self.outputs = outputs
        self.inputs: list[Any] = []

    async def ainvoke(self, value: Any, config: dict[str, Any]) -> dict[str, Any]:
        self.inputs.append(value)
        return self.outputs.pop(0)

    async def astream(self, value: Any, config: dict[str, Any], stream_mode: list[str]) -> Any:
        del stream_mode
        self.inputs.append(value)
        yield "values", self.outputs.pop(0)


class FakeStreamingGraph:
    async def astream(self, value: Any, config: dict[str, Any], stream_mode: list[str]) -> Any:
        del value, config, stream_mode
        yield "messages", (AIMessageChunk(content="Ciao"), {})
        yield "values", {"messages": [AIMessage(content="Ciao")]}


def fake_harness(
    graph: FakeGraph,
    continuations: int = 3,
    grader: Any = None,
    escalation_threshold: float = 0.5,
) -> Any:
    return SimpleNamespace(
        graph=graph,
        settings=SimpleNamespace(
            harness_max_continuations=continuations,
            harness_escalation_threshold=escalation_threshold,
        ),
        # Il runner fa salire la scala quando un'iterazione non supera il criterio di uscita.
        ladder=TierLadder(),
        grader=grader,
    )


def test_final_text_excludes_encrypted_reasoning_blocks() -> None:
    message = AIMessage(
        content=[
            {"type": "reasoning", "encrypted_content": "must-not-leak"},
            {"type": "text", "text": "Risposta visibile"},
        ]
    )

    assert final_text([message]) == "Risposta visibile"


@pytest.mark.asyncio
async def test_runner_emits_streamed_assistant_text() -> None:
    events: list[dict[str, Any]] = []
    result = await GoalRunner(
        fake_harness(FakeStreamingGraph()),  # type: ignore[arg-type]
        event_callback=events.append,
    ).run("Saluta", thread_id="stream")

    assert result.text == "Ciao"
    assert events == [{"type": "assistant.delta", "text": "Ciao"}]


@pytest.mark.asyncio
async def test_runner_stops_on_completion_marker() -> None:
    graph = FakeGraph([{"messages": [AIMessage(content="Fatto. [GOAL_COMPLETE]")]}])
    result = await GoalRunner(fake_harness(graph)).run("Rispondi alla domanda", thread_id="t-1")
    assert result.completed is True
    assert result.iterations == 1


@pytest.mark.asyncio
async def test_runner_reinjects_goal_until_budget() -> None:
    graph = FakeGraph(
        [
            {"messages": [AIMessage(content="Non ancora")]},
            {"messages": [AIMessage(content="Ancora incompleto")]},
        ]
    )
    result = await GoalRunner(fake_harness(graph, 2)).run("Crea un file", thread_id="t-2")
    assert result.completed is False
    assert result.iterations == 2
    assert "Crea un file" in graph.inputs[1]["messages"][0]["content"]


@pytest.mark.asyncio
async def test_mutating_goal_requires_successful_sandbox_verification() -> None:
    graph = FakeGraph(
        [
            {"messages": [AIMessage(content="Fatto. [GOAL_COMPLETE]")]},
            {
                "messages": [
                    ToolMessage(
                        content="exit_code=0\nSTDOUT:\nok",
                        tool_call_id="call-1",
                        name="docker_exec",
                    ),
                    AIMessage(content="Verificato. [GOAL_COMPLETE]"),
                ]
            },
        ]
    )
    result = await GoalRunner(fake_harness(graph, 2)).run("Crea un file", thread_id="t-5")
    assert result.completed is True
    assert result.iterations == 2


@pytest.mark.asyncio
async def test_runner_accepts_when_grader_passes() -> None:
    graph = FakeGraph([{"messages": [AIMessage(content="Ecco la risposta. [GOAL_COMPLETE]")]}])
    grader = FakeGrader([GradeResult(passed=True, score=0.9, feedback="")])
    events: list[dict[str, Any]] = []
    result = await GoalRunner(
        fake_harness(graph, grader=grader),
        event_callback=events.append,
    ).run("Rispondi alla domanda", thread_id="g-1")

    assert result.completed is True
    assert result.iterations == 1
    assert len(grader.calls) == 1
    assert {event["type"] for event in events} == {"grader.started", "grader.completed"}
    completed = next(event for event in events if event["type"] == "grader.completed")
    assert completed["feedback"] == ""
    assert completed["criteria_scores"] == {}


@pytest.mark.asyncio
async def test_runner_reinjects_feedback_when_grader_fails() -> None:
    graph = FakeGraph(
        [
            {"messages": [AIMessage(content="Prima risposta. [GOAL_COMPLETE]")]},
            {"messages": [AIMessage(content="Risposta corretta. [GOAL_COMPLETE]")]},
        ]
    )
    grader = FakeGrader(
        [
            GradeResult(passed=False, score=0.4, feedback="Manca la verifica dei risultati."),
            GradeResult(passed=True, score=0.85, feedback=""),
        ]
    )
    result = await GoalRunner(fake_harness(graph, 2, grader)).run(
        "Rispondi alla domanda", thread_id="g-2"
    )

    assert result.completed is True
    assert result.iterations == 2
    assert "Manca la verifica dei risultati." in graph.inputs[1]["messages"][0]["content"]


@pytest.mark.asyncio
async def test_runner_requires_approval_callback() -> None:
    graph = FakeGraph([{"__interrupt__": [Interrupt(value={"action": "docker_exec"}, id="1")]}])
    with pytest.raises(RuntimeError, match="callback"):
        await GoalRunner(fake_harness(graph)).run("Esegui test", thread_id="t-3")


@pytest.mark.asyncio
async def test_runner_matches_decisions_to_parallel_hanging_tool_calls() -> None:
    """Regressione: due tool sensibili chiamati nello stesso turno devono ricevere
    una decisione ciascuno, altrimenti HumanInTheLoopMiddleware.after_model solleva
    ValueError ("Number of human decisions does not match...") e il run va in crash."""
    graph = FakeGraph(
        [
            {
                "__interrupt__": [
                    Interrupt(
                        value={
                            "action_requests": [
                                {"name": "docker_exec", "args": {"command": "npm install"}},
                                {
                                    "name": "docker_exec",
                                    "args": {"command": "apt-get install -y chromium"},
                                },
                            ]
                        },
                        id="1",
                    )
                ]
            },
            {"messages": [AIMessage(content="Fatto. [GOAL_COMPLETE]")]},
        ]
    )

    async def approve(_: dict[str, Any]) -> bool:
        return True

    result = await GoalRunner(fake_harness(graph), approval_callback=approve).run(
        "Esegui due comandi sensibili", thread_id="t-multi"
    )

    assert result.completed is True
    resumed_command = graph.inputs[1]
    assert resumed_command.resume["decisions"] == [{"type": "approve"}, {"type": "approve"}]


@pytest.mark.asyncio
async def test_user_action_interrupt_routes_to_interaction_callback() -> None:
    """Un interrupt di tipo user_action va al callback di interazione e riprende con la
    risposta dell'utente, non con il formato decisioni dell'approvazione."""
    graph = FakeGraph(
        [
            {
                "__interrupt__": [
                    Interrupt(
                        value={
                            "type": "user_action",
                            "title": "Autorizza",
                            "instructions": "Apri il link e incolla il codice",
                            "response_kind": "value",
                        },
                        id="1",
                    )
                ]
            },
            {"messages": [AIMessage(content="Fatto. [GOAL_COMPLETE]")]},
        ]
    )
    seen: dict[str, Any] = {}

    async def interaction(payload: dict[str, Any]) -> dict[str, Any]:
        seen.update(payload)
        return {"response": "code-xyz"}

    async def approve(_: dict[str, Any]) -> bool:  # non deve essere usato
        raise AssertionError("approval non deve gestire user_action")

    result = await GoalRunner(
        fake_harness(graph),
        approval_callback=approve,
        interaction_callback=interaction,
    ).run("Collega un account esterno", thread_id="t-action")

    assert result.completed is True
    assert seen["type"] == "user_action"
    # Riprende con la risposta grezza dell'utente, non con {"decisions": ...}.
    assert graph.inputs[1].resume == {"response": "code-xyz"}


@pytest.mark.asyncio
async def test_user_action_without_interaction_callback_raises() -> None:
    graph = FakeGraph(
        [{"__interrupt__": [Interrupt(value={"type": "user_action"}, id="1")]}]
    )
    with pytest.raises(RuntimeError, match="callback"):
        await GoalRunner(fake_harness(graph)).run("Azione utente", thread_id="t-a2")


@pytest.mark.asyncio
async def test_empty_goal_is_rejected() -> None:
    graph = FakeGraph([])
    with pytest.raises(ValueError):
        await GoalRunner(fake_harness(graph)).run(" ", thread_id="t-4")

@pytest.mark.asyncio
async def test_a_failed_iteration_climbs_the_ladder_and_announces_it() -> None:
    """Il cuore dell'escalation: non si prevede la difficoltà, la si misura."""
    graph = FakeGraph(
        [
            {"messages": [AIMessage(content="Tentativo debole. [GOAL_COMPLETE]")]},
            {"messages": [AIMessage(content="Ora è giusta. [GOAL_COMPLETE]")]},
        ]
    )
    grader = FakeGrader(
        [
            GradeResult(passed=False, score=0.4, feedback="Manca la verifica."),
            GradeResult(passed=True, score=0.9, feedback=""),
        ]
    )
    harness = fake_harness(graph, 2, grader)
    eventi: list[dict[str, object]] = []

    result = await GoalRunner(harness, event_callback=eventi.append).run(
        "Rispondi", thread_id="esc-1"
    )

    assert result.completed is True
    assert harness.ladder.current == "mid"
    salite = [e for e in eventi if e["type"] == "model.escalated"]
    assert salite == [{"type": "model.escalated", "tier": "mid", "iteration": 2}]


@pytest.mark.asyncio
async def test_a_borderline_score_retries_on_the_same_rung_instead_of_paying_more() -> None:
    """Fra la soglia di uscita (0.7) e quella di escalation (0.5) si riprova, non si sale.

    Misurato sull'eval set: 3 risposte corrette su 16 prendono fra 0.61 e 0.67. Salire su
    ognuna significherebbe comprare il modello caro per un lavoro già fatto bene.
    """
    graph = FakeGraph(
        [
            {"messages": [AIMessage(content="Quasi. [GOAL_COMPLETE]")]},
            {"messages": [AIMessage(content="Ecco. [GOAL_COMPLETE]")]},
        ]
    )
    grader = FakeGrader(
        [
            GradeResult(passed=False, score=0.65, feedback="Manca un dettaglio."),
            GradeResult(passed=True, score=0.9, feedback=""),
        ]
    )
    harness = fake_harness(graph, 2, grader)
    eventi: list[dict[str, object]] = []

    result = await GoalRunner(harness, event_callback=eventi.append).run("x", thread_id="bord")

    assert result.completed is True
    assert result.iterations == 2
    assert harness.ladder.current == "low"
    assert not [e for e in eventi if e["type"] == "model.escalated"]


@pytest.mark.asyncio
async def test_a_failed_environment_verification_climbs_even_without_a_grade() -> None:
    """Il criterio di uscita ha due gambe: il grader e la verifica riuscita nella sandbox."""
    graph = FakeGraph(
        [
            {"messages": [AIMessage(content="Ho scritto il file.")]},
            {"messages": [AIMessage(content="Ora verificato.")]},
        ]
    )
    harness = fake_harness(graph, 2, grader=None)
    eventi: list[dict[str, object]] = []

    # "Scrivi" attiva `requires_environment_verification`, e nessun ToolMessage docker_exec
    # con exit_code=0 compare fra i messaggi: la verifica non è riuscita.
    await GoalRunner(harness, event_callback=eventi.append).run(
        "Scrivi /workspace/x.txt", thread_id="verif"
    )

    assert harness.ladder.current == "mid"
    assert [e["tier"] for e in eventi if e["type"] == "model.escalated"] == ["mid"]


@pytest.mark.asyncio
async def test_a_run_that_passes_first_time_never_leaves_the_cheapest_tier() -> None:
    graph = FakeGraph([{"messages": [AIMessage(content="Giusta subito. [GOAL_COMPLETE]")]}])
    grader = FakeGrader([GradeResult(passed=True, score=0.9, feedback="")])
    harness = fake_harness(graph, 3, grader)
    eventi: list[dict[str, object]] = []

    await GoalRunner(harness, event_callback=eventi.append).run("Rispondi", thread_id="esc-2")

    assert harness.ladder.current == "low"
    assert not [e for e in eventi if e["type"] == "model.escalated"]


@pytest.mark.asyncio
async def test_the_ladder_does_not_climb_past_the_top() -> None:
    """Con tre iterazioni fallite si arriva a `high` e ci si resta: non esiste un quarto gradino."""
    graph = FakeGraph([{"messages": [AIMessage(content=f"Tentativo {i}.")]} for i in range(4)])
    grader = FakeGrader([GradeResult(passed=False, score=0.2, feedback="no") for _ in range(4)])
    harness = fake_harness(graph, 4, grader)
    eventi: list[dict[str, object]] = []

    result = await GoalRunner(harness, event_callback=eventi.append).run("x", thread_id="esc-3")

    assert result.completed is False
    assert harness.ladder.current == "high"
    assert [e["tier"] for e in eventi if e["type"] == "model.escalated"] == ["mid", "high"]


@pytest.mark.asyncio
async def test_a_second_goal_starts_again_from_the_bottom() -> None:
    graph = FakeGraph(
        [
            {"messages": [AIMessage(content="a")]},
            {"messages": [AIMessage(content="b. [GOAL_COMPLETE]")]},
            {"messages": [AIMessage(content="c. [GOAL_COMPLETE]")]},
        ]
    )
    grader = FakeGrader(
        [
            GradeResult(passed=False, score=0.3, feedback="no"),
            GradeResult(passed=True, score=0.9, feedback=""),
            GradeResult(passed=True, score=0.9, feedback=""),
        ]
    )
    harness = fake_harness(graph, 2, grader)
    runner = GoalRunner(harness)

    await runner.run("primo obiettivo difficile", thread_id="esc-4")
    assert harness.ladder.current == "mid"

    await runner.run("secondo obiettivo facile", thread_id="esc-4")
    assert harness.ladder.current == "low"
