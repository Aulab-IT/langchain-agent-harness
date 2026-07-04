from types import SimpleNamespace
from typing import Any

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
from langgraph.types import Interrupt

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


def fake_harness(graph: FakeGraph, continuations: int = 3, grader: Any = None) -> Any:
    return SimpleNamespace(
        graph=graph,
        settings=SimpleNamespace(harness_max_continuations=continuations),
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
async def test_empty_goal_is_rejected() -> None:
    graph = FakeGraph([])
    with pytest.raises(ValueError):
        await GoalRunner(fake_harness(graph)).run(" ", thread_id="t-4")
