import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from langchain_core.tools import tool
from langgraph.errors import GraphInterrupt

from agent_harness.audit import AuditMiddleware
from agent_harness.config import Settings
from agent_harness.factory import _builtin_subagents, _resolve_subagent
from agent_harness.subagents import (
    delete_subagent,
    load_subagent_specs,
    read_subagent,
    write_subagent,
)


def spec(name: str = "research-notes") -> dict[str, object]:
    return {
        "name": name,
        "description": "Raccoglie note verificabili.",
        "system_prompt": "Cerca dati e restituisci fonti.",
        "model_tier": "mid",
        "capabilities": ["ricerca bibliografica", "confronto fonti"],
        "inputs": ["domanda di ricerca"],
        "outputs": ["sintesi con URL"],
        "constraints": ["cita fonti verificabili"],
        "tools": ["search"],
        "read_only": True,
    }


def test_subagent_crud_and_markdown_roundtrip(tmp_path: Path) -> None:
    saved = write_subagent(tmp_path, spec())

    assert saved["name"] == "research-notes"
    assert saved["valid"] is True
    assert "model_tier: mid" in (tmp_path / "research-notes.md").read_text(encoding="utf-8")
    assert read_subagent(tmp_path, "research-notes")["tools"] == ["search"]
    assert saved["capabilities"] == ["ricerca bibliografica", "confronto fonti"]
    loaded, warnings = load_subagent_specs(tmp_path)
    assert warnings == []
    assert loaded[0]["outputs"] == ["sintesi con URL"]

    delete_subagent(tmp_path, "research-notes")
    with pytest.raises(FileNotFoundError):
        read_subagent(tmp_path, "research-notes")


def test_subagent_rejects_traversal_and_name_file_mismatch(tmp_path: Path) -> None:
    invalid = spec("../escape")
    with pytest.raises(ValueError, match="name"):
        write_subagent(tmp_path, invalid)

    (tmp_path / "actual.md").write_text(
        "---\nname: other\ndescription: desc\n---\n\nprompt\n", encoding="utf-8"
    )
    specs, warnings = load_subagent_specs(tmp_path)
    assert specs == []
    assert "nome file" in warnings[0]


def test_subagent_invalid_tier_is_ignored_with_warning(tmp_path: Path) -> None:
    (tmp_path / "bad.md").write_text(
        "---\nname: bad\ndescription: desc\nmodel_tier: giant\n---\n\nprompt\n",
        encoding="utf-8",
    )
    specs, warnings = load_subagent_specs(tmp_path)
    assert specs == []
    assert "model_tier" in warnings[0]


def test_subagent_invalid_routing_metadata_is_ignored_with_warning(tmp_path: Path) -> None:
    (tmp_path / "bad.md").write_text(
        "---\nname: bad\ndescription: desc\ncapabilities: nope\n---\n\nprompt\n",
        encoding="utf-8",
    )
    specs, warnings = load_subagent_specs(tmp_path)
    assert specs == []
    assert "capabilities" in warnings[0]


def test_settings_creates_subagents_directory(tmp_path: Path) -> None:
    settings = Settings(_env_file=None, project_root=tmp_path)
    settings.ensure_directories()
    assert settings.subagents_dir.is_dir()


@tool
def search(query: str) -> str:
    """Search fixture."""
    return query


@tool
def docker_exec(command: str) -> str:
    """Sandbox fixture."""
    return command


def test_resolve_subagent_filters_unknown_tools_and_overrides_builtin() -> None:
    tiers = {
        "low": SimpleNamespace(model="low-model"),
        "mid": SimpleNamespace(model="mid-model"),
        "high": SimpleNamespace(model="high-model"),
    }
    resolved, unknown = _resolve_subagent(
        {**spec("reviewer"), "tools": ["search", "gone"]}, [search], tiers
    )  # type: ignore[arg-type]
    merged = _builtin_subagents([search], tiers)  # type: ignore[arg-type]
    merged[resolved["name"]] = resolved

    assert unknown == ["gone"]
    assert [item.name for item in resolved["tools"]] == ["search"]
    assert resolved["model"] == "mid-model"
    assert merged["reviewer"]["system_prompt"] == "Cerca dati e restituisci fonti."
    assert merged["reviewer"]["permissions"]


def test_subagent_with_sandbox_can_request_dependency_installation() -> None:
    tiers = {
        "low": SimpleNamespace(model="low-model"),
        "mid": SimpleNamespace(model="mid-model"),
        "high": SimpleNamespace(model="high-model"),
    }
    resolved, unknown = _resolve_subagent(
        {**spec("builder"), "tools": ["docker_exec"]}, [docker_exec], tiers
    )  # type: ignore[arg-type]

    prompt = str(resolved["system_prompt"])
    assert unknown == []
    assert "with_network=true" in prompt
    assert "approvare o rifiutare" in prompt
    assert "/workspace/.pylib" in prompt


@pytest.mark.asyncio
async def test_subagent_telemetry_keeps_parallel_invocations_correlated(tmp_path: Path) -> None:
    events: list[dict[str, object]] = []
    tool_observations: list[dict[str, object]] = []
    observed: list[str] = []
    semaphore = asyncio.Semaphore(2)
    parent = AuditMiddleware(
        tmp_path / "audit.jsonl",
        events.append,
        task_semaphore=semaphore,
        task_observer=observed.append,
    )
    child = AuditMiddleware(
        tmp_path / "audit.jsonl",
        events.append,
        subagent_name="researcher",
        tool_observer=tool_observations.append,
    )

    async def invoke(call_id: str) -> None:
        task_request = SimpleNamespace(
            tool_call={
                "id": call_id,
                "name": "task",
                "args": {"subagent_type": "researcher", "description": call_id},
            }
        )
        child_request = SimpleNamespace(
            tool_call={"id": f"child-{call_id}", "name": "search", "args": {"q": call_id}}
        )

        async def child_handler(_: object):
            await asyncio.sleep(0)
            return "ok"

        async def parent_handler(_: object):
            return await child.awrap_tool_call(child_request, child_handler)

        await parent.awrap_tool_call(task_request, parent_handler)

    await asyncio.gather(invoke("one"), invoke("two"))
    child_events = [event for event in events if event["type"] == "subagent.tool.started"]
    assert {event["invocation_id"] for event in child_events} == {"one", "two"}
    assert {event["parent_tool_call_id"] for event in child_events} == {"one", "two"}
    assert observed == ["researcher", "researcher"]
    completed = [
        event for event in tool_observations if event["type"] == "subagent.tool.completed"
    ]
    assert {event["invocation_id"] for event in completed} == {"one", "two"}


@pytest.mark.asyncio
async def test_audit_injects_dag_context_and_emits_task_metadata(tmp_path: Path) -> None:
    events: list[dict[str, object]] = []
    task = SimpleNamespace(id="deck", depends_on=["research"])
    execution = SimpleNamespace(
        task=task,
        attempt=1,
        status="running",
        objective_met=False,
        input_artifacts=["output/research.json"],
        output_artifacts=[],
    )

    class Coordinator:
        async def prepare_delegation(
            self, subagent: str, description: str, call_id: str
        ) -> tuple[object, str]:
            assert (subagent, call_id) == ("presentation-maker", "call-deck")
            return execution, f"{description}\nInjected predecessor result"

        def complete_delegation(
            self, current: object, *, result: object = None, error: Exception | None = None
        ) -> None:
            assert current is execution and error is None and result == "created"
            execution.status = "completed"
            execution.objective_met = True
            execution.output_artifacts = ["output/deck.pptx"]

    class Request:
        def __init__(self, tool_call: dict[str, object]) -> None:
            self.tool_call = tool_call

        def override(self, **values: object) -> "Request":
            return Request(values["tool_call"])  # type: ignore[arg-type]

    middleware = AuditMiddleware(
        tmp_path / "audit.jsonl", events.append, task_coordinator=Coordinator()
    )
    request = Request(
        {
            "id": "call-deck",
            "name": "task",
            "args": {"subagent_type": "presentation-maker", "description": "Crea deck"},
        }
    )
    captured = ""

    async def handler(prepared: Request) -> str:
        nonlocal captured
        captured = str(prepared.tool_call["args"])
        return "created"

    await middleware.awrap_tool_call(request, handler)  # type: ignore[arg-type,return-value]

    assert "Injected predecessor result" in captured
    assert [event["type"] for event in events] == [
        "subagent.started",
        "subagent.completed",
    ]
    assert events[-1]["routing_task_id"] == "deck"
    assert events[-1]["objective_met"] is True
    assert events[-1]["output_artifacts"] == ["output/deck.pptx"]


@pytest.mark.asyncio
async def test_audit_treats_graph_interrupt_as_pause_and_resume(tmp_path: Path) -> None:
    events: list[dict[str, object]] = []
    task = SimpleNamespace(id="deck", depends_on=[])
    execution = SimpleNamespace(
        task=task,
        attempt=1,
        status="running",
        resumed=False,
        objective_met=False,
        input_artifacts=[],
        output_artifacts=[],
    )

    class Coordinator:
        async def prepare_delegation(
            self, _subagent: str, description: str, _call_id: str
        ) -> tuple[object, str]:
            return execution, description

        def pause_delegation(self, current: object) -> None:
            assert current is execution
            execution.status = "paused"

        def complete_delegation(
            self, current: object, *, result: object = None, error: Exception | None = None
        ) -> None:
            assert current is execution and error is None and result == "done"
            execution.status = "completed"
            execution.objective_met = True

    class Request:
        def __init__(self) -> None:
            self.tool_call = {
                "id": "same-call",
                "name": "task",
                "args": {"subagent_type": "worker", "description": "crea"},
            }

        def override(self, **_values: object) -> "Request":
            return self

    middleware = AuditMiddleware(
        tmp_path / "audit.jsonl", events.append, task_coordinator=Coordinator()
    )
    request = Request()

    async def interrupted(_: Request) -> str:
        raise GraphInterrupt()

    with pytest.raises(GraphInterrupt):
        await middleware.awrap_tool_call(request, interrupted)  # type: ignore[arg-type,return-value]

    execution.resumed = True

    async def completed(_: Request) -> str:
        return "done"

    await middleware.awrap_tool_call(request, completed)  # type: ignore[arg-type,return-value]

    assert [event["type"] for event in events] == [
        "subagent.started",
        "subagent.paused",
        "subagent.resumed",
        "subagent.completed",
    ]
    assert "subagent.failed" not in {event["type"] for event in events}
    assert '"status": "paused"' in (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
