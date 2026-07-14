import asyncio
import json
from typing import Any

import pytest
from langchain.agents.middleware import ModelRequest, ToolCallRequest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from agent_harness.subagent_routing import (
    DelegationPlan,
    RootToolRoute,
    RoutedTask,
    SubagentProfile,
    SubagentRouterMiddleware,
    ToolProfile,
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


def tool_profile(
    name: str = "mcp__service__inspect__12345678",
    *,
    origin: str = "mcp:service",
) -> ToolProfile:
    return ToolProfile(
        identity=f"{origin}:inspect",
        name=name,
        display_name="inspect",
        origin=origin,
        server="service" if origin.startswith("mcp:") else None,
        description="Inspect current external service state.",
        arguments=["scope"],
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
        kind="work",
        required_tools=[],
        required_capabilities=[],
        requires_write=False,
        success_criteria=["risultato verificabile"],
    )


def completed(text: str, *, verdict: str | None = None) -> AIMessage:
    suffix = f"\nVERDICT: {verdict}" if verdict else ""
    return AIMessage(
        content=f"{text}\nTASK_STATUS: COMPLETE\nEVIDENCE:\n- verifica concreta{suffix}"
    )


def test_routing_prompt_contains_dynamic_contract_not_name_rules() -> None:
    prompt = routing_prompt(
        "Prepara il risultato",
        [profile("worker-a")],
        [tool_profile()],
    )

    assert '"name": "worker-a"' in prompt
    assert '"capabilities"' in prompt
    assert '"constraints"' in prompt
    assert "Never infer routing" in prompt
    assert "from an agent's name" in prompt
    assert '"expected_output"' in prompt
    assert "AVAILABLE ROOT TOOLS JSON" in prompt
    assert '"external_data_required"' in prompt
    assert '"mcp:service"' in prompt
    assert "particular server or" in prompt
    assert "workspace artifacts" in prompt
    assert "Tool possession alone is not specialization" in prompt


def test_validate_plan_requires_known_runtime_tool_independently_from_external_state() -> None:
    candidate = tool_profile()
    external = DelegationPlan(
        delegate=False,
        rationale="direct",
        tasks=[],
        root_tools=RootToolRoute(
            required=True,
            external_data_required=True,
            candidates=[candidate.name, "invented"],
            rationale="live state",
        ),
    )

    validated = validate_plan(external, [], [candidate])

    assert validated.root_tools.required is True
    assert validated.root_tools.candidates == [candidate.name]

    workspace_action = external.model_copy(
        update={
            "root_tools": RootToolRoute(
                required=True,
                external_data_required=False,
                candidates=[candidate.name],
                rationale="workspace action",
            )
        }
    )
    validated_workspace = validate_plan(workspace_action, [], [candidate])
    assert validated_workspace.root_tools.required is True
    assert validated_workspace.root_tools.external_data_required is False

    informational = workspace_action.model_copy(
        update={
            "root_tools": RootToolRoute(
                required=False,
                external_data_required=False,
                candidates=[candidate.name],
                rationale="optional lookup",
            )
        }
    )
    validated_info = validate_plan(informational, [], [candidate])
    assert validated_info.root_tools.required is False


def test_single_tool_task_with_irrelevant_agent_is_redirected_to_root() -> None:
    docker = tool_profile("docker_exec", origin="built-in")
    presenter = SubagentProfile(
        name="presentation-maker",
        description="Crea presentazioni PowerPoint.",
        capabilities=[
            "creazione di presentazioni PowerPoint",
            "verifica visuale e tecnica del deck",
        ],
        outputs=["presentazione finale verificata"],
        tools=["docker_exec"],
        read_only=False,
    )
    merge = RoutedTask(
        id="merge-documents",
        objective="Unisci i due PDF e salva il documento risultante.",
        selected_agent=presenter.name,
        alternatives=[],
        reason="Unico agente con docker_exec",
        depends_on=[],
        expected_output="output/merged.pdf",
        kind="work",
        required_tools=["docker_exec"],
        # Capability copiate dal profilo non devono rendere circolare il match.
        required_capabilities=list(presenter.capabilities),
        requires_write=True,
        success_criteria=["PDF risultante valido"],
    )
    diagnostics: list[dict[str, Any]] = []

    validated = validate_plan(
        DelegationPlan(delegate=True, rationale="delegate", tasks=[merge]),
        [presenter],
        [docker],
        diagnostics=diagnostics,
    )

    assert validated.delegate is False
    assert validated.tasks == []
    assert validated.root_tools.required is True
    assert validated.root_tools.external_data_required is False
    assert validated.root_tools.candidates == ["docker_exec"]
    assert diagnostics[0]["agent"] == presenter.name
    assert "semantic mismatch" in diagnostics[0]["reason"]


def test_single_tool_task_keeps_objective_relevant_specialist() -> None:
    docker = tool_profile("docker_exec", origin="built-in")
    presenter = SubagentProfile(
        name="presentation-maker",
        description="Crea presentazioni PowerPoint.",
        capabilities=["creazione di presentazioni PowerPoint"],
        outputs=["presentazione finale verificata"],
        tools=["docker_exec"],
        read_only=False,
    )
    deck = RoutedTask(
        id="deck",
        objective="Crea una presentazione PowerPoint dai materiali forniti.",
        selected_agent=presenter.name,
        alternatives=[],
        reason="Specialista pertinente",
        depends_on=[],
        expected_output="output/deck.pptx",
        kind="work",
        required_tools=["docker_exec"],
        required_capabilities=list(presenter.capabilities),
        requires_write=True,
        success_criteria=["Presentazione valida"],
    )

    validated = validate_plan(
        DelegationPlan(delegate=True, rationale="specialization", tasks=[deck]),
        [presenter],
        [docker],
    )

    assert validated.delegate is True
    assert [item.selected_agent for item in validated.tasks] == [presenter.name]


def test_structured_output_schema_is_strict_for_openai() -> None:
    schema = DelegationPlan.model_json_schema()
    task_schema = schema["$defs"]["RoutedTask"]

    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {"delegate", "rationale", "tasks", "root_tools"}
    tool_route_schema = schema["$defs"]["RootToolRoute"]
    assert tool_route_schema["additionalProperties"] is False
    assert set(tool_route_schema["required"]) == {
        "required",
        "external_data_required",
        "candidates",
        "rationale",
    }
    assert task_schema["additionalProperties"] is False
    assert set(task_schema["required"]) == {
        "id",
        "objective",
        "selected_agent",
        "alternatives",
        "reason",
        "depends_on",
        "expected_output",
        "kind",
        "required_tools",
        "required_capabilities",
        "requires_write",
        "success_criteria",
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


def test_validate_plan_reassigns_only_to_capability_compatible_agent() -> None:
    readonly = profile("worker-a").model_copy(update={"read_only": True})
    writer = profile("worker-b")
    planned = task("write", "worker-a").model_copy(
        update={
            "alternatives": ["worker-b"],
            "requires_write": True,
            "required_tools": ["artifact_write"],
            "required_capabilities": ["sintesi strutturata"],
        }
    )

    result = validate_plan(
        DelegationPlan(delegate=True, rationale="write", tasks=[planned]),
        [readonly, writer],
    )

    assert result.delegate is True
    assert result.tasks[0].selected_agent == "worker-b"
    assert result.tasks[0].alternatives == []


def test_validate_plan_drops_task_and_descendants_when_no_agent_has_required_tool() -> None:
    source = task("source", "worker-a").model_copy(update={"required_tools": ["skill_create"]})
    review = task("review", "worker-b", depends_on=["source"])

    result = validate_plan(
        DelegationPlan(delegate=True, rationale="unsupported", tasks=[source, review]),
        [profile("worker-a"), profile("worker-b")],
    )

    assert result.delegate is False
    assert result.tasks == []


def test_validate_plan_uses_independent_agent_for_review() -> None:
    work = task("work", "worker-a")
    review = task("review", "worker-a", depends_on=["work"]).model_copy(
        update={"kind": "review", "alternatives": ["worker-b"]}
    )

    result = validate_plan(
        DelegationPlan(delegate=True, rationale="review", tasks=[work, review]),
        [profile("worker-a"), profile("worker-b")],
    )

    assert result.tasks[1].selected_agent == "worker-b"


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
        "tool.routing.completed",
    ]
    assert events[1]["decision"] == "delegation_useful"
    assert events[1]["rejected_matches"] == []


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


def test_middleware_trace_explains_irrelevant_match_redirected_to_root() -> None:
    worker = profile("artifact-worker")
    root_tool = tool_profile("artifact_write", origin="built-in")
    routed = task("merge", worker.name, objective="Unisci due PDF")
    routed = routed.model_copy(
        update={
            "alternatives": [],
            "expected_output": "output/merged.pdf",
            "required_tools": ["artifact_write"],
            # Valore realmente esposto, ma non pertinente alla fusione PDF.
            "required_capabilities": ["sintesi strutturata"],
            "requires_write": True,
        }
    )
    events: list[dict[str, Any]] = []
    router = SubagentRouterMiddleware(  # type: ignore[arg-type]
        FakeModel(DelegationPlan(delegate=True, rationale="tool match", tasks=[routed])),
        [worker],
        tools=[root_tool],
        event_callback=events.append,
    )
    request = ModelRequest(  # type: ignore[arg-type]
        model=FakeModel(DelegationPlan(delegate=False, rationale="unused", tasks=[])),
        messages=[HumanMessage(content="Unisci questi PDF")],
        tools=[],
    )

    router.wrap_model_call(request, lambda _: "ok")  # type: ignore[arg-type,return-value]

    routing = next(event for event in events if event["type"] == "subagent.routing.completed")
    tools = next(event for event in events if event["type"] == "tool.routing.completed")
    assert routing["decision"] == "direct_root"
    assert routing["delegate"] is False
    assert routing["rejected_matches"][0]["agent"] == worker.name
    assert tools["required"] is True
    assert tools["recommended"] == ["artifact_write"]


def test_middleware_retries_with_json_when_structured_output_is_unsupported() -> None:
    raw = AIMessage(
        content=(
            '{"delegate": true, "rationale": "match", "tasks": ['
            '{"id": "one", "objective": "crea", "selected_agent": "worker-a", '
            '"alternatives": [], "reason": "profilo", "depends_on": [], '
            '"expected_output": "artefatto", "kind": "work", '
            '"required_tools": [], "required_capabilities": [], '
            '"requires_write": false, "success_criteria": ["artefatto presente"]}]}'
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
        "tool.routing.completed",
    ]
    assert events[-1]["strategy"] == "json"


def test_middleware_initializes_when_provider_has_no_structured_output() -> None:
    candidate = tool_profile()
    raw = AIMessage(
        content=json.dumps(
            {
                "delegate": False,
                "rationale": "direct",
                "tasks": [],
                "root_tools": {
                    "required": True,
                    "external_data_required": True,
                    "candidates": [candidate.name],
                    "rationale": "live state",
                },
            }
        )
    )
    model = FakeModelWithoutStructuredOutput(RuntimeError("unused"), raw)
    events: list[dict[str, Any]] = []

    router = SubagentRouterMiddleware(  # type: ignore[arg-type]
        model,
        [profile("worker-a")],
        tools=[candidate],
        event_callback=events.append,
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
        "tool.routing.completed",
    ]
    assert events[1]["reason"] == "provider has no structured output"
    assert events[-1]["strategy"] == "json"
    assert events[-1]["recommended"] == [candidate.name]


@pytest.mark.asyncio
async def test_async_middleware_falls_back_when_provider_has_no_structured_output() -> None:
    raw = AIMessage(content='{"delegate": false, "rationale": "direct", "tasks": []}')
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
        "tool.routing.completed",
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
        result=completed("Tre paper verificati: https://example.test/paper"),
    )
    deck, prepared = await router.prepare_delegation(
        "presentation-maker", "[routing_task_id=deck] Crea deck", "call-deck"
    )
    assert "Validated predecessor results" in prepared
    assert "https://example.test/paper" in prepared
    router.complete_delegation(
        deck,
        result=completed("Creato file /workspace/output/deck.pptx con 8 slide."),
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
        router.prepare_delegation("worker-b", "[routing_task_id=deliver] consegna", "deliver-call")
    )
    await asyncio.sleep(0)
    assert not pending.done()

    source, _ = await router.prepare_delegation(
        "worker-a", "[routing_task_id=source] raccogli", "source-call"
    )

    router.complete_delegation(source, result=completed("Dati verificati completi."))
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
    router.complete_delegation(resumed, result=completed("Risultato completo verificato."))
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
        result=completed("Creato **/workspace/output/deck.pptx** e verificato."),
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
        execution, result=completed("Presentazione creata e verificata correttamente.")
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
        source_execution, result=completed("Ricerca completata e verificata.")
    )
    deck_execution, _ = await router.prepare_delegation(
        "worker-b", "[routing_task_id=deck] crea", "deck-call"
    )
    router.complete_delegation(
        deck_execution, result=completed("Elaborazione completata senza nuovo file.")
    )

    assert deck_execution is not None
    assert deck_execution.status == "incomplete"
    assert deck_execution.output_artifacts == []


@pytest.mark.asyncio
async def test_incomplete_plan_blocks_root_and_can_reassign_to_planned_alternative() -> None:
    planned = task("deck", "worker-a").model_copy(update={"alternatives": ["worker-b"]})
    plan = DelegationPlan(delegate=True, rationale="fallback", tasks=[planned])
    events: list[dict[str, Any]] = []
    router = SubagentRouterMiddleware(  # type: ignore[arg-type]
        FakeModel(plan),
        [profile("worker-a"), profile("worker-b")],
        event_callback=events.append,
    )
    request = ModelRequest(  # type: ignore[arg-type]
        model=FakeModel(plan), messages=[HumanMessage(content="Crea")], tools=[]
    )
    router.wrap_model_call(request, lambda _: "ok")  # type: ignore[arg-type,return-value]
    first, _ = await router.prepare_delegation("worker-a", "[routing_task_id=deck] crea", "call-a")
    router.complete_delegation(first, result=AIMessage(content="Mi manca il materiale."))

    passed, feedback = router.completion_check("Crea", [])
    assert passed is False
    assert "worker-b" in feedback

    retry, _ = await router.prepare_delegation(
        "worker-b", "[routing_task_id=deck] riprova", "call-b"
    )
    router.complete_delegation(
        retry, result=completed("Risultato completo e verificato correttamente.")
    )

    assert router.completion_check("Crea", []) == (True, "")
    assert any(event["type"] == "subagent.task.reassigned" for event in events)


@pytest.mark.asyncio
async def test_required_tool_must_be_observed_before_task_can_complete() -> None:
    planned = task("research", "worker-a").model_copy(update={"required_tools": ["artifact_write"]})
    plan = DelegationPlan(delegate=True, rationale="evidence", tasks=[planned])
    router = SubagentRouterMiddleware(FakeModel(plan), [profile("worker-a")])  # type: ignore[arg-type]
    request = ModelRequest(  # type: ignore[arg-type]
        model=FakeModel(plan), messages=[HumanMessage(content="Ricerca")], tools=[]
    )
    router.wrap_model_call(request, lambda _: "ok")  # type: ignore[arg-type,return-value]

    execution, _ = await router.prepare_delegation(
        "worker-a", "[routing_task_id=research] esegui", "call-one"
    )
    router.complete_delegation(execution, result=completed("Risultato dichiarato completo."))
    assert execution is not None and execution.status == "incomplete"

    retry, _ = await router.prepare_delegation(
        "worker-a", "[routing_task_id=research] riprova", "call-two"
    )
    router.record_tool_event(
        {
            "type": "subagent.tool.completed",
            "routing_task_id": "research",
            "attempt": 2,
            "tool": "artifact_write",
        }
    )
    router.complete_delegation(retry, result=completed("Risultato verificato con tool."))
    assert retry is not None and retry.status == "completed"
    assert retry.used_tools == ["artifact_write"]


def test_required_root_tool_blocks_completion_until_recommended_tool_succeeds() -> None:
    candidate = tool_profile()
    plan = DelegationPlan(
        delegate=False,
        rationale="direct external lookup",
        tasks=[],
        root_tools=RootToolRoute(
            required=True,
            external_data_required=True,
            candidates=[candidate.name],
            rationale="current external state required",
        ),
    )
    events: list[dict[str, Any]] = []
    router = SubagentRouterMiddleware(  # type: ignore[arg-type]
        FakeModel(plan), [], tools=[candidate], event_callback=events.append
    )
    request = ModelRequest(  # type: ignore[arg-type]
        model=FakeModel(plan), messages=[HumanMessage(content="Mostra stato corrente")], tools=[]
    )
    router.wrap_model_call(request, lambda _: "ok")  # type: ignore[arg-type,return-value]

    passed, feedback = router.tool_completion_check("", [])
    assert passed is False
    assert candidate.name in feedback

    tool_request = ToolCallRequest(  # type: ignore[arg-type]
        tool_call={"id": "external-one", "name": candidate.name, "args": {}},
        tool=None,
        state={},
        runtime=None,
    )
    router.wrap_tool_call(
        tool_request,
        lambda _: ToolMessage(
            content="live result", tool_call_id="external-one", name=candidate.name
        ),
    )

    assert router.tool_completion_check("", []) == (True, "")
    routing = next(event for event in events if event["type"] == "tool.routing.completed")
    assert routing["recommended"] == [candidate.name]
    assert any(event["type"] == "tool.routing.used" for event in events)


@pytest.mark.asyncio
async def test_completed_dag_exposes_evidence_and_delegated_sandbox_verification() -> None:
    plan = DelegationPlan(delegate=True, rationale="evidence", tasks=[task("deck", "worker-a")])
    model = FakeModel(plan)
    router = SubagentRouterMiddleware(model, [profile("worker-a")])  # type: ignore[arg-type]
    request = ModelRequest(  # type: ignore[arg-type]
        model=model, messages=[HumanMessage(content="Crea")], tools=[]
    )
    router.wrap_model_call(request, lambda _: "ok")  # type: ignore[arg-type,return-value]
    execution, _ = await router.prepare_delegation(
        "worker-a", "[routing_task_id=deck] crea", "call-one"
    )
    router.record_tool_event(
        {
            "type": "subagent.tool.completed",
            "routing_task_id": "deck",
            "attempt": 1,
            "tool": "docker_exec",
            "output": "exit_code=0\nSTDOUT: 8 slides valid",
        }
    )
    router.complete_delegation(
        execution, result=completed("Presentazione creata e controllata: output/deck.pptx")
    )

    assert router.has_successful_environment_verification() is True
    evidence = router.completion_evidence()
    assert "output/deck.pptx" in evidence
    assert "Sandbox verified: yes" in evidence

    captured: list[ModelRequest[Any]] = []
    router.wrap_model_call(  # type: ignore[arg-type]
        request, lambda next_request: captured.append(next_request) or "ok"
    )
    system = captured[0].system_message
    assert system is not None
    assert "finalization mode" in system.text
    assert "Do not recreate a plan" in system.text
    assert "Execute this validated plan" not in system.text

    tool_request = ToolCallRequest(  # type: ignore[arg-type]
        tool_call={"id": "todo-one", "name": "write_todos", "args": {}},
        tool=None,
        state={},
        runtime=None,
    )
    tool_result = router.wrap_tool_call(  # type: ignore[arg-type]
        tool_request, lambda _: pytest.fail("completed DAG must not execute more tools")
    )
    assert isinstance(tool_result, ToolMessage)
    assert "already complete" in str(tool_result.content)


@pytest.mark.asyncio
async def test_review_requires_explicit_pass_verdict() -> None:
    planned = task("review", "worker-a").model_copy(update={"kind": "review"})
    plan = DelegationPlan(delegate=True, rationale="review", tasks=[planned])
    router = SubagentRouterMiddleware(FakeModel(plan), [profile("worker-a")])  # type: ignore[arg-type]
    request = ModelRequest(  # type: ignore[arg-type]
        model=FakeModel(plan), messages=[HumanMessage(content="Verifica")], tools=[]
    )
    router.wrap_model_call(request, lambda _: "ok")  # type: ignore[arg-type,return-value]

    failed, _ = await router.prepare_delegation(
        "worker-a", "[routing_task_id=review] verifica", "review-one"
    )
    router.complete_delegation(
        failed, result=completed("Trovati difetti bloccanti.", verdict="FAIL")
    )
    assert failed is not None and failed.status == "incomplete"

    passed, _ = await router.prepare_delegation(
        "worker-a", "[routing_task_id=review] riverifica", "review-two"
    )
    router.complete_delegation(
        passed, result=completed("Tutti i criteri risultano verificati.", verdict="PASS")
    )
    assert passed is not None and passed.status == "completed"


@pytest.mark.asyncio
async def test_preexisting_artifact_claim_is_rejected_but_modified_hash_is_accepted() -> None:
    planned = task("deck", "worker-a").model_copy(
        update={"expected_output": "File PowerPoint .pptx"}
    )
    plan = DelegationPlan(delegate=True, rationale="provenance", tasks=[planned])
    snapshot = {"output/deck.pptx": "old-hash"}
    router = SubagentRouterMiddleware(  # type: ignore[arg-type]
        FakeModel(plan),
        [profile("worker-a")],
        artifact_validator=lambda path: path == "output/deck.pptx",
        artifact_snapshotter=lambda: snapshot,
    )
    request = ModelRequest(  # type: ignore[arg-type]
        model=FakeModel(plan), messages=[HumanMessage(content="Crea")], tools=[]
    )
    router.wrap_model_call(request, lambda _: "ok")  # type: ignore[arg-type,return-value]

    unchanged, _ = await router.prepare_delegation(
        "worker-a", "[routing_task_id=deck] crea", "deck-one"
    )
    router.complete_delegation(unchanged, result=completed("Creato /workspace/output/deck.pptx"))
    assert unchanged is not None and unchanged.status == "incomplete"
    assert unchanged.output_artifacts == []

    modified, _ = await router.prepare_delegation(
        "worker-a", "[routing_task_id=deck] modifica", "deck-two"
    )
    snapshot["output/deck.pptx"] = "new-hash"
    router.complete_delegation(modified, result=completed("Aggiornato /workspace/output/deck.pptx"))
    assert modified is not None and modified.status == "completed"
    assert modified.output_artifacts == ["output/deck.pptx"]
