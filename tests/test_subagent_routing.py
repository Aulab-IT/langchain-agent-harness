import asyncio
from typing import Any

import pytest
from langchain.agents.middleware import ModelRequest
from langchain_core.messages import AIMessage, HumanMessage

from agent_harness.subagent_routing import (
    DelegationPlan,
    RoutedTask,
    SubagentProfile,
    SubagentRouterMiddleware,
    parse_json_plan,
    render_plan,
    routing_prompt,
    validate_plan,
)


class FakeStructuredPlanner:
    def __init__(self, result: DelegationPlan | Exception) -> None:
        self.result = result
        self.calls = 0

    def invoke(self, _messages: object) -> DelegationPlan:
        self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class FakeModel:
    def __init__(
        self,
        result: DelegationPlan | Exception,
        raw_result: AIMessage | Exception | None = None,
    ) -> None:
        self.planner = FakeStructuredPlanner(result)
        self.raw_result = raw_result or RuntimeError("raw fallback unavailable")
        self.raw_calls = 0

    def with_structured_output(self, _schema: object) -> FakeStructuredPlanner:
        return self.planner

    def invoke(self, _messages: object) -> AIMessage:
        self.raw_calls += 1
        if isinstance(self.raw_result, Exception):
            raise self.raw_result
        return self.raw_result

    async def ainvoke(self, _messages: object) -> AIMessage:
        return self.invoke(_messages)


class FakeModelWithoutStructuredOutput(FakeModel):
    def with_structured_output(self, _schema: object) -> FakeStructuredPlanner:
        raise NotImplementedError("provider has no structured output")


def profile(name: str) -> SubagentProfile:
    return SubagentProfile(
        name=name,
        description="Trasforma dati in un artefatto verificabile.",
        capabilities=["sintesi strutturata"],
        inputs=["note sorgente"],
        outputs=["artefatto finale"],
        constraints=["non inventare fonti"],
        tools=["artifact_write"],
        model_tier="mid",
    )


def task(
    task_id: str,
    agent: str,
    *,
    objective: str = "Crea artefatto",
    depends_on: list[str] | None = None,
) -> RoutedTask:
    return RoutedTask(
        id=task_id,
        objective=objective,
        selected_agent=agent,
        alternatives=["worker-b", "invented", agent],
        reason="Profilo compatibile",
        depends_on=depends_on or [],
        expected_output="artefatto",
    )


def test_routing_prompt_contains_dynamic_contract_not_name_rules() -> None:
    prompt = routing_prompt("Prepara il risultato", [profile("worker-a")])

    assert '"name": "worker-a"' in prompt
    assert '"capabilities"' in prompt
    assert '"constraints"' in prompt
    assert "Never infer routing" in prompt
    assert "from an agent's name" in prompt
    assert '"expected_output"' in prompt


def test_structured_output_schema_is_strict_for_openai() -> None:
    schema = DelegationPlan.model_json_schema()
    task_schema = schema["$defs"]["RoutedTask"]

    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {"delegate", "rationale", "tasks"}
    assert task_schema["additionalProperties"] is False
    assert set(task_schema["required"]) == {
        "id",
        "objective",
        "selected_agent",
        "alternatives",
        "reason",
        "depends_on",
        "expected_output",
    }


def test_json_fallback_extracts_fenced_plan() -> None:
    raw = AIMessage(
        content='```json\n{"delegate": false, "rationale": "diretto", "tasks": []}\n```'
    )

    plan = parse_json_plan(raw)

    assert plan.delegate is False
    assert plan.rationale == "diretto"


def test_validate_plan_removes_hallucinated_agents_and_invalid_dependencies() -> None:
    profiles = [profile("worker-a"), profile("worker-b")]
    raw = DelegationPlan(
        delegate=True,
        rationale="Serve isolamento.",
        tasks=[
            task("source", "worker-a"),
            task("deliver", "worker-b", depends_on=["source", "missing", "source"]),
            task("unknown", "invented"),
            task("source", "worker-b"),
        ],
    )

    result = validate_plan(raw, profiles)

    assert result.delegate is True
    assert [item.id for item in result.tasks] == ["source", "deliver"]
    assert result.tasks[0].alternatives == ["worker-b"]
    assert result.tasks[1].depends_on == ["source"]


def test_validate_plan_rejects_dependency_cycles() -> None:
    profiles = [profile("worker-a")]
    raw = DelegationPlan(
        delegate=True,
        rationale="Ciclo invalido.",
        tasks=[
            task("one", "worker-a", depends_on=["two"]),
            task("two", "worker-a", depends_on=["one"]),
        ],
    )

    result = validate_plan(raw, profiles)

    assert result.delegate is False
    assert result.tasks == []
    assert "cicliche" in result.rationale


def test_render_plan_exposes_agent_and_dependency_order() -> None:
    plan = DelegationPlan(
        delegate=True,
        rationale="Due passaggi dipendenti.",
        tasks=[
            task("source", "worker-a"),
            task("deliver", "worker-b", depends_on=["source"]),
        ],
    )

    rendered = render_plan(plan)

    assert "`source` → `worker-a`" in rendered
    assert "`deliver` → `worker-b`" in rendered
    assert "depends_on: source" in rendered
    assert "runtime DAG coordination" in rendered


def test_middleware_plans_once_injects_route_and_emits_trace() -> None:
    plan = DelegationPlan(
        delegate=True, rationale="Match semantico", tasks=[task("one", "worker-a")]
    )
    model = FakeModel(plan)
    events: list[dict[str, Any]] = []
    router = SubagentRouterMiddleware(  # type: ignore[arg-type]
        model, [profile("worker-a")], event_callback=events.append
    )
    request = ModelRequest(  # type: ignore[arg-type]
        model=model,
        messages=[HumanMessage(content="Crea il risultato")],
        tools=[],
    )
    captured: list[ModelRequest[Any]] = []

    def handler(next_request: ModelRequest[Any]) -> Any:
        captured.append(next_request)
        return "ok"

    assert router.wrap_model_call(request, handler) == "ok"  # type: ignore[arg-type]
    assert router.wrap_model_call(request, handler) == "ok"  # type: ignore[arg-type]

    assert model.planner.calls == 1
    assert captured[0].system_message is not None
    assert "`one` → `worker-a`" in captured[0].system_message.text
    assert [event["type"] for event in events] == [
        "subagent.routing.started",
        "subagent.routing.completed",
    ]


def test_middleware_falls_back_without_mutating_request_when_planner_fails() -> None:
    model = FakeModel(RuntimeError("structured output unavailable"))
    events: list[dict[str, Any]] = []
    router = SubagentRouterMiddleware(  # type: ignore[arg-type]
        model, [profile("worker-a")], event_callback=events.append
    )
    request = ModelRequest(  # type: ignore[arg-type]
        model=model,
        messages=[HumanMessage(content="Crea il risultato")],
        tools=[],
    )
    captured: list[ModelRequest[Any]] = []

    def handler(next_request: ModelRequest[Any]) -> Any:
        captured.append(next_request)
        return "ok"

    router.wrap_model_call(request, handler)  # type: ignore[arg-type]

    assert captured[0].system_message is None
    assert events[-1]["type"] == "subagent.routing.failed"


def test_middleware_retries_with_json_when_structured_output_is_unsupported() -> None:
    raw = AIMessage(
        content=(
            '{"delegate": true, "rationale": "match", "tasks": ['
            '{"id": "one", "objective": "crea", "selected_agent": "worker-a", '
            '"alternatives": [], "reason": "profilo", "depends_on": [], '
            '"expected_output": "artefatto"}]}'
        )
    )
    model = FakeModel(RuntimeError("schema unsupported"), raw)
    events: list[dict[str, Any]] = []
    router = SubagentRouterMiddleware(  # type: ignore[arg-type]
        model, [profile("worker-a")], event_callback=events.append
    )
    request = ModelRequest(  # type: ignore[arg-type]
        model=model,
        messages=[HumanMessage(content="Crea")],
        tools=[],
    )

    router.wrap_model_call(request, lambda _: "ok")  # type: ignore[arg-type,return-value]

    assert model.raw_calls == 1
    assert [event["type"] for event in events] == [
        "subagent.routing.started",
        "subagent.routing.retry",
        "subagent.routing.completed",
    ]
    assert events[-1]["strategy"] == "json"


def test_middleware_initializes_when_provider_has_no_structured_output() -> None:
    raw = AIMessage(
        content='{"delegate": false, "rationale": "direct", "tasks": []}'
    )
    model = FakeModelWithoutStructuredOutput(RuntimeError("unused"), raw)
    events: list[dict[str, Any]] = []

    router = SubagentRouterMiddleware(  # type: ignore[arg-type]
        model, [profile("worker-a")], event_callback=events.append
    )
    request = ModelRequest(  # type: ignore[arg-type]
        model=model,
        messages=[HumanMessage(content="Crea")],
        tools=[],
    )
    router.wrap_model_call(request, lambda _: "ok")  # type: ignore[arg-type,return-value]

    assert model.raw_calls == 1
    assert [event["type"] for event in events] == [
        "subagent.routing.started",
        "subagent.routing.retry",
        "subagent.routing.completed",
    ]
    assert events[1]["reason"] == "provider has no structured output"
    assert events[-1]["strategy"] == "json"


@pytest.mark.asyncio
async def test_async_middleware_falls_back_when_provider_has_no_structured_output() -> None:
    raw = AIMessage(
        content='{"delegate": false, "rationale": "direct", "tasks": []}'
    )
    model = FakeModelWithoutStructuredOutput(RuntimeError("unused"), raw)
    events: list[dict[str, Any]] = []
    router = SubagentRouterMiddleware(  # type: ignore[arg-type]
        model, [profile("worker-a")], event_callback=events.append
    )
    request = ModelRequest(  # type: ignore[arg-type]
        model=model,
        messages=[HumanMessage(content="Crea")],
        tools=[],
    )

    async def handler(_: ModelRequest[Any]) -> Any:
        return "ok"

    await router.awrap_model_call(request, handler)  # type: ignore[arg-type]

    assert model.raw_calls == 1
    assert [event["type"] for event in events] == [
        "subagent.routing.started",
        "subagent.routing.retry",
        "subagent.routing.completed",
    ]
    assert events[-1]["strategy"] == "json"


@pytest.mark.asyncio
async def test_research_then_presentation_plan_is_executed_end_to_end() -> None:
    profiles = [profile("researcher"), profile("presentation-maker")]
    plan = DelegationPlan(
        delegate=True,
        rationale="Ricerca alimenta presentazione.",
        tasks=[
            task("research", "researcher", objective="Trova cinque paper"),
            task(
                "deck",
                "presentation-maker",
                objective="Crea PowerPoint dai paper",
                depends_on=["research"],
            ),
        ],
    )
    model = FakeModel(plan)
    events: list[dict[str, Any]] = []
    router = SubagentRouterMiddleware(  # type: ignore[arg-type]
        model, profiles, event_callback=events.append
    )
    request = ModelRequest(  # type: ignore[arg-type]
        model=model,
        messages=[HumanMessage(content="Cerca paper e crea una presentazione")],
        tools=[],
    )

    router.wrap_model_call(request, lambda _: "ok")  # type: ignore[arg-type,return-value]
    research, _ = await router.prepare_delegation(
        "researcher", "[routing_task_id=research] Trova paper", "call-research"
    )
    router.complete_delegation(
        research,
        result=AIMessage(content="Tre paper verificati: https://example.test/paper"),
    )
    deck, prepared = await router.prepare_delegation(
        "presentation-maker", "[routing_task_id=deck] Crea deck", "call-deck"
    )
    assert "Validated predecessor results" in prepared
    assert "https://example.test/paper" in prepared
    router.complete_delegation(
        deck,
        result=AIMessage(content="Creato file /workspace/output/deck.pptx con 8 slide."),
    )
    router.finalize()

    assert events[-1]["type"] == "subagent.routing.followed"
    assert events[-1]["task_ids"] == ["research", "deck"]
    assert not any(event["type"] == "subagent.routing.not_followed" for event in events)


@pytest.mark.asyncio
async def test_dependency_waits_and_receives_predecessor_output() -> None:
    plan = DelegationPlan(
        delegate=True,
        rationale="DAG",
        tasks=[
            task("source", "worker-a", objective="Raccogli dati"),
            task("deliver", "worker-b", depends_on=["source"]),
        ],
    )
    router = SubagentRouterMiddleware(  # type: ignore[arg-type]
        FakeModel(plan), [profile("worker-a"), profile("worker-b")]
    )
    request = ModelRequest(  # type: ignore[arg-type]
        model=FakeModel(plan), messages=[HumanMessage(content="Crea")], tools=[]
    )
    router.wrap_model_call(request, lambda _: "ok")  # type: ignore[arg-type,return-value]

    pending = asyncio.create_task(
        router.prepare_delegation(
            "worker-b", "[routing_task_id=deliver] consegna", "deliver-call"
        )
    )
    await asyncio.sleep(0)
    assert not pending.done()

    source, _ = await router.prepare_delegation(
        "worker-a", "[routing_task_id=source] raccogli", "source-call"
    )

    router.complete_delegation(source, result=AIMessage(content="Dati verificati completi."))
    deliver, prepared = await pending

    assert deliver is not None
    assert "Dati verificati completi" in prepared


@pytest.mark.asyncio
async def test_incomplete_output_does_not_mark_routing_followed() -> None:
    planned = task("deck", "worker-a")
    planned = planned.model_copy(update={"expected_output": "File PowerPoint .pptx"})
    plan = DelegationPlan(delegate=True, rationale="deck", tasks=[planned])
    model = FakeModel(plan)
    events: list[dict[str, Any]] = []
    router = SubagentRouterMiddleware(  # type: ignore[arg-type]
        model, [profile("worker-a")], event_callback=events.append
    )
    request = ModelRequest(  # type: ignore[arg-type]
        model=model, messages=[HumanMessage(content="Crea deck")], tools=[]
    )
    router.wrap_model_call(request, lambda _: "ok")  # type: ignore[arg-type,return-value]
    execution, _ = await router.prepare_delegation(
        "worker-a", "[routing_task_id=deck] crea", "deck-call"
    )
    router.complete_delegation(
        execution,
        result=AIMessage(content="Mi manca il materiale necessario, forniscilo per procedere."),
    )
    router.finalize()

    assert any(event["type"] == "subagent.task.incomplete" for event in events)
    assert events[-1]["type"] == "subagent.routing.not_followed"
    assert events[-1]["unresolved_tasks"][0]["status"] == "incomplete"


@pytest.mark.asyncio
async def test_approval_pause_resumes_same_execution_without_retry() -> None:
    plan = DelegationPlan(
        delegate=True,
        rationale="approval",
        tasks=[task("deck", "worker-a")],
    )
    events: list[dict[str, Any]] = []
    router = SubagentRouterMiddleware(  # type: ignore[arg-type]
        FakeModel(plan), [profile("worker-a")], event_callback=events.append
    )
    request = ModelRequest(  # type: ignore[arg-type]
        model=FakeModel(plan), messages=[HumanMessage(content="Crea")], tools=[]
    )
    router.wrap_model_call(request, lambda _: "ok")  # type: ignore[arg-type,return-value]

    first, prepared = await router.prepare_delegation(
        "worker-a", "[routing_task_id=deck] crea", "same-call"
    )
    router.pause_delegation(first)
    resumed, resumed_prepared = await router.prepare_delegation(
        "worker-a", "[routing_task_id=deck] crea", "same-call"
    )

    assert resumed is first
    assert resumed is not None and resumed.attempt == 1 and resumed.resumed is True
    assert resumed_prepared == prepared
    router.complete_delegation(resumed, result=AIMessage(content="Risultato completo verificato."))
    router.finalize()

    types = [event["type"] for event in events]
    assert "subagent.task.paused" in types
    assert "subagent.task.resumed" in types
    assert "subagent.task.failed" not in types
    assert types.count("subagent.task.queued") == 1
    assert events[-1]["type"] == "subagent.routing.followed"


@pytest.mark.asyncio
async def test_markdown_wrapped_artifact_path_is_normalized_and_validated() -> None:
    planned = task("deck", "worker-a").model_copy(
        update={"expected_output": "File PowerPoint .pptx"}
    )
    plan = DelegationPlan(delegate=True, rationale="deck", tasks=[planned])
    events: list[dict[str, Any]] = []
    router = SubagentRouterMiddleware(  # type: ignore[arg-type]
        FakeModel(plan),
        [profile("worker-a")],
        event_callback=events.append,
        artifact_validator=lambda path: path == "output/deck.pptx",
    )
    request = ModelRequest(  # type: ignore[arg-type]
        model=FakeModel(plan), messages=[HumanMessage(content="Crea deck")], tools=[]
    )
    router.wrap_model_call(request, lambda _: "ok")  # type: ignore[arg-type,return-value]
    execution, _ = await router.prepare_delegation(
        "worker-a", "[routing_task_id=deck] crea", "deck-call"
    )

    router.complete_delegation(
        execution,
        result=AIMessage(content="Creato **/workspace/output/deck.pptx** e verificato."),
    )

    assert execution is not None
    assert execution.status == "completed"
    assert execution.output_artifacts == ["output/deck.pptx"]


@pytest.mark.asyncio
async def test_new_output_file_reconciles_missing_text_claim() -> None:
    planned = task("deck", "worker-a").model_copy(
        update={"expected_output": "File PowerPoint .pptx"}
    )
    plan = DelegationPlan(delegate=True, rationale="deck", tasks=[planned])
    listed: list[str] = []
    router = SubagentRouterMiddleware(  # type: ignore[arg-type]
        FakeModel(plan),
        [profile("worker-a")],
        artifact_validator=lambda path: path == "output/deck.pptx",
        artifact_lister=lambda: listed,
    )
    request = ModelRequest(  # type: ignore[arg-type]
        model=FakeModel(plan), messages=[HumanMessage(content="Crea deck")], tools=[]
    )
    router.wrap_model_call(request, lambda _: "ok")  # type: ignore[arg-type,return-value]
    execution, _ = await router.prepare_delegation(
        "worker-a", "[routing_task_id=deck] crea", "deck-call"
    )
    listed.append("output/deck.pptx")

    router.complete_delegation(
        execution, result=AIMessage(content="Presentazione creata e verificata correttamente.")
    )

    assert execution is not None
    assert execution.status == "completed"
    assert execution.output_artifacts == ["output/deck.pptx"]


@pytest.mark.asyncio
async def test_dependency_artifact_is_not_claimed_as_downstream_output() -> None:
    source = task("source", "worker-a", objective="Raccogli dati")
    deliver = task("deck", "worker-b", depends_on=["source"]).model_copy(
        update={"expected_output": "File PowerPoint .pptx"}
    )
    plan = DelegationPlan(delegate=True, rationale="dag", tasks=[source, deliver])
    listed: list[str] = []
    router = SubagentRouterMiddleware(  # type: ignore[arg-type]
        FakeModel(plan),
        [profile("worker-a"), profile("worker-b")],
        artifact_validator=lambda path: path in listed,
        artifact_lister=lambda: listed,
    )
    request = ModelRequest(  # type: ignore[arg-type]
        model=FakeModel(plan), messages=[HumanMessage(content="Crea")], tools=[]
    )
    router.wrap_model_call(request, lambda _: "ok")  # type: ignore[arg-type,return-value]

    source_execution, _ = await router.prepare_delegation(
        "worker-a", "[routing_task_id=source] cerca", "source-call"
    )
    listed.append("output/source.pptx")
    router.complete_delegation(
        source_execution, result=AIMessage(content="Ricerca completata e verificata.")
    )
    deck_execution, _ = await router.prepare_delegation(
        "worker-b", "[routing_task_id=deck] crea", "deck-call"
    )
    router.complete_delegation(
        deck_execution, result=AIMessage(content="Elaborazione completata senza nuovo file.")
    )

    assert deck_execution is not None
    assert deck_execution.status == "incomplete"
    assert deck_execution.output_artifacts == []
