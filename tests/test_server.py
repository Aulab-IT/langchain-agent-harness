import itertools
import json
from collections.abc import Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

import agent_harness.server as server
from agent_harness.command_review import payload_wants_network
from agent_harness.config import Settings
from agent_harness.control_store import ControlStore
from agent_harness.durable import DurableStore
from agent_harness.improve import Proposal, write_proposal
from agent_harness.runner import RunResult
from agent_harness.usage import context_categories


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    (tmp_path / ".agents" / "skills").mkdir(parents=True)
    (tmp_path / "memories").mkdir()
    (tmp_path / "memories" / "AGENTS.md").write_text("# Test\n", encoding="utf-8")
    settings = Settings(_env_file=None, project_root=tmp_path, openai_api_key=None)
    isolated_store = ControlStore(settings)
    # Storage durevole isolato per il test: senza, gli interrupt/trigger finirebbero nel
    # durable.sqlite reale creato all'import del modulo.
    isolated_durable = DurableStore(tmp_path / "durable.sqlite")
    monkeypatch.setattr(server, "settings", settings)
    monkeypatch.setattr(server, "store", isolated_store)
    monkeypatch.setattr(server, "durable_store", isolated_durable)
    monkeypatch.setattr(server, "run_manager", server.RunManager())
    with TestClient(server.app) as test_client:
        yield test_client
    isolated_store.close()
    isolated_durable.close()


def test_status_exposes_runtime_without_secrets(client: TestClient) -> None:
    response = client.get("/api/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["backend"] == "online"
    assert "openai_api_key" not in payload
    assert "docker_exec" in {tool["name"] for tool in payload["tools"]}


def test_human_rejection_overrides_model_success() -> None:
    result = RunResult(
        text="Fatto",
        iterations=1,
        completed=True,
        messages=[],
    )

    assert server._terminal_outcome(
        result,
        "blocked_needs_human",
        "Approvazione rifiutata.",
    ) == ("blocked_needs_human", False, "Approvazione rifiutata.")


@pytest.mark.parametrize(
    ("emit_verification", "expected_status"),
    [(True, "completed"), (False, "failed_verification")],
)
@pytest.mark.asyncio
async def test_evidence_contract_gates_completed_runs(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    emit_verification: bool,
    expected_status: str,
) -> None:
    session = client.post("/api/sessions", json={"title": "Evidence gate"}).json()
    run = server.store.create_run(session["id"])

    async def no_preflight(*args: object, **kwargs: object) -> None:
        return None

    @asynccontextmanager
    async def fake_build_harness(*args: object, **kwargs: object) -> object:
        if emit_verification:
            callback = kwargs["event_callback"]
            callback(
                {
                    "type": "tool.started",
                    "tool": "docker_exec",
                    "tool_call_id": "verify-1",
                    "args": '{"command":"test -f report.txt"}',
                }
            )
            callback(
                {
                    "type": "tool.completed",
                    "tool": "docker_exec",
                    "tool_call_id": "verify-1",
                    "output": "exit_code=0 STDOUT: verified",
                }
            )
        yield SimpleNamespace(completion_checks=[])

    class FakeGoalRunner:
        def __init__(self, *args: object, **kwargs: object) -> None:
            self.last_messages: list[object] = []

        async def run(self, goal: str, *, thread_id: str) -> RunResult:
            del goal, thread_id
            messages = [AIMessage(content="Report creato e verificato")]
            self.last_messages = messages
            return RunResult(
                text="Report creato e verificato",
                iterations=1,
                completed=True,
                messages=messages,
            )

    monkeypatch.setattr(server.provider_cfg, "validate_overrides", lambda _: [])
    monkeypatch.setattr(server, "preflight_tier_models", no_preflight)
    monkeypatch.setattr(server, "load_subagent_specs", lambda _: ([], []))
    monkeypatch.setattr(server, "build_harness", fake_build_harness)
    monkeypatch.setattr(server, "GoalRunner", FakeGoalRunner)

    await server.run_manager._execute(
        run["id"], session["id"], "Crea un report per il deploy"
    )

    saved = server.store.get_run(run["id"])
    assert saved["status"] == expected_status
    response = client.get(f"/api/runs/{run['id']}/evidence")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["manifest"]["contract"]["passed"] is emit_verification
    assert payload["integrity"]["valid"] is True
    assert payload["checker"]["passed"] is emit_verification
    assert payload["manifest"]["delivery"]["relevant"] is True
    if emit_verification:
        decision = client.post(
            f"/api/runs/{run['id']}/delivery-gate",
            json={"decision": "approved", "note": "Review umana completata"},
        )
        assert decision.status_code == 200
        assert decision.json()["delivery_gate"]["decision"] == "approved"
        assert decision.json()["delivery"]["ready"] is False
        assert next(
            check
            for check in decision.json()["delivery"]["checks"]
            if check["id"] == "human_gate"
        )["passed"] is True
        oversized = client.post(
            f"/api/runs/{run['id']}/delivery-gate",
            json={"decision": "approved", "note": "x" * 501},
        )
        assert oversized.status_code == 422
    else:
        decision = client.post(
            f"/api/runs/{run['id']}/delivery-gate",
            json={"decision": "approved"},
        )
        assert decision.status_code == 409
    assert any(
        event["type"] == "evidence.manifest.created"
        for event in server.store.list_events(run["id"])
    )


@pytest.mark.asyncio
async def test_incomplete_runner_result_is_persisted_as_failed_verification(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = client.post("/api/sessions", json={"title": "Outcome"}).json()
    run = server.store.create_run(session["id"])

    async def no_preflight(*args: object, **kwargs: object) -> None:
        return None

    @asynccontextmanager
    async def fake_build_harness(*args: object, **kwargs: object) -> object:
        yield SimpleNamespace(completion_checks=[])

    class FakeGoalRunner:
        def __init__(self, *args: object, **kwargs: object) -> None:
            self.last_messages: list[object] = []

        async def run(self, goal: str, *, thread_id: str) -> RunResult:
            del goal, thread_id
            messages = [AIMessage(content="Output parziale")]
            self.last_messages = messages
            return RunResult(
                text="Output parziale",
                iterations=3,
                completed=False,
                messages=messages,
                terminal_status="failed_verification",
                failure_reason="Delega pianificata non completata.",
            )

    monkeypatch.setattr(server.provider_cfg, "validate_overrides", lambda _: [])
    monkeypatch.setattr(server, "preflight_tier_models", no_preflight)
    monkeypatch.setattr(server, "load_subagent_specs", lambda _: ([], []))
    monkeypatch.setattr(server, "build_harness", fake_build_harness)
    monkeypatch.setattr(server, "GoalRunner", FakeGoalRunner)

    await server.run_manager._execute(run["id"], session["id"], "Analizza")

    saved = server.store.get_run(run["id"])
    assert saved["status"] == "failed_verification"
    assert saved["error"] == "Delega pianificata non completata."
    events = server.store.list_events(run["id"])
    assert any(event["type"] == "run.failed_verification" for event in events)
    assert not any(event["type"] == "run.completed" for event in events)


@pytest.mark.asyncio
async def test_budget_exceeded_during_preflight_is_persisted_with_budget_snapshot(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = client.post("/api/sessions", json={"title": "Preflight budget"}).json()
    run = server.store.create_run(session["id"])

    async def blocked_preflight(
        *args: object,
        budget_tracker: object | None = None,
        **kwargs: object,
    ) -> None:
        del args, kwargs
        assert budget_tracker is not None
        budget_tracker.exceed("cost", "Preflight fuori budget.")  # type: ignore[attr-defined]

    monkeypatch.setattr(server.provider_cfg, "validate_overrides", lambda _: [])
    monkeypatch.setattr(server, "preflight_tier_models", blocked_preflight)
    monkeypatch.setattr(server, "load_subagent_specs", lambda _: ([], []))

    await server.run_manager._execute(run["id"], session["id"], "Rispondi OK")

    saved = server.store.get_run(run["id"])
    assert saved["status"] == "budget_exceeded"
    assert saved["error"] == "Preflight fuori budget."
    assert saved["usage"]["budget"]["exceeded_dimension"] == "cost"
    assert saved["usage"]["budget"]["exceeded"] is True
    events = server.store.list_events(run["id"])
    assert any(event["type"] == "run.budget_exceeded" for event in events)


@pytest.mark.asyncio
async def test_provider_failure_preserves_usage_error_details_and_artifacts(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = client.post("/api/sessions", json={"title": "Provider failure"}).json()
    run = server.store.create_run(session["id"])

    async def no_preflight(*args: object, **kwargs: object) -> None:
        return None

    @asynccontextmanager
    async def fake_build_harness(*args: object, **kwargs: object) -> object:
        yield SimpleNamespace(completion_checks=[], budget_tracker=None)

    class APIError(Exception):
        def __init__(self) -> None:
            super().__init__("Retry your request. Request ID req_preserved123")
            self.body = {"type": "server_error", "code": "stream_failed"}
            self.request_id = "req_preserved123"

    class FakeGoalRunner:
        def __init__(self, harness: object, *args: object, **kwargs: object) -> None:
            del args, kwargs
            self.harness = harness
            self.last_messages = [AIMessage(content="Lavoro quasi concluso")]

        async def run(self, goal: str, *, thread_id: str) -> RunResult:
            del goal
            output = server.store.workspace_dir(thread_id) / "output" / "report.txt"
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text("verified partial result", encoding="utf-8")
            raise APIError()

    monkeypatch.setattr(server.provider_cfg, "validate_overrides", lambda _: [])
    monkeypatch.setattr(server, "preflight_tier_models", no_preflight)
    monkeypatch.setattr(server, "load_subagent_specs", lambda _: ([], []))
    monkeypatch.setattr(server, "build_harness", fake_build_harness)
    monkeypatch.setattr(server, "GoalRunner", FakeGoalRunner)

    await server.run_manager._execute(run["id"], session["id"], "Crea report")

    saved = server.store.get_run(run["id"])
    assert saved["status"] == "incomplete"
    assert saved["usage"]
    assert "req_preserved123" in saved["error"]
    events = server.store.list_events(run["id"])
    model_error = next(event for event in events if event["type"] == "model.error")
    assert model_error["payload"]["request_id"] == "req_preserved123"
    assert model_error["payload"]["provider_error_code"] == "stream_failed"
    partial = next(event for event in events if event["type"] == "run.partial_result")
    assert partial["payload"]["attachments"] == ["output/report.txt"]


def test_status_exposes_the_three_rungs_with_their_price(client: TestClient) -> None:
    models = client.get("/api/status").json()["models"]

    assert [model["tier"] for model in models] == ["low", "mid", "high"]
    # Il costo deve crescere lungo la scala, altrimenti «sali solo se serve» non vuol dire nulla.
    for cheaper, dearer in itertools.pairwise(models):
        assert cheaper["price_in"] < dearer["price_in"]
        assert cheaper["price_out"] < dearer["price_out"]
    assert models[0]["effort"] == "low"
    assert models[2]["effort"] == "high"


def test_tools_endpoint_describes_real_tools_with_their_arguments(client: TestClient) -> None:
    response = client.get("/api/tools")

    assert response.status_code == 200
    tools = {tool["name"]: tool for tool in response.json()}
    # Il vecchio elenco letterale annunciava un tool "mcp:local_harness" inesistente.
    assert "mcp:local_harness" not in tools
    assert tools["docker_exec"]["origin"] == "built-in"

    arguments = {arg["name"]: arg for arg in tools["docker_exec"]["arguments"]}
    assert arguments["command"]["required"] is True
    assert arguments["with_network"]["required"] is False
    assert arguments["with_network"]["type"] == "boolean"
    assert tools["docker_exec"]["description"]


def test_subagent_api_crud_and_validation(client: TestClient) -> None:
    payload = {
        "name": "web-research",
        "description": "Ricerca fonti.",
        "system_prompt": "Trova URL verificabili.",
        "model_tier": "low",
        "capabilities": ["ricerca web"],
        "inputs": ["domanda"],
        "outputs": ["sintesi con URL"],
        "constraints": ["solo fonti pubbliche"],
        "tools": ["web_search"],
        "read_only": True,
    }
    created = client.post("/api/subagents", json=payload)
    assert created.status_code == 201
    assert created.json()["read_only"] is True
    assert created.json()["capabilities"] == ["ricerca web"]
    assert client.post("/api/subagents", json=payload).status_code == 409

    listed = client.get("/api/subagents")
    assert listed.status_code == 200
    assert [item["name"] for item in listed.json()] == ["web-research"]

    updated = client.put(
        "/api/subagents/web-research",
        json={**payload, "description": "Ricerca fonti recenti."},
    )
    assert updated.status_code == 200
    assert updated.json()["description"] == "Ricerca fonti recenti."
    assert client.delete("/api/subagents/web-research").status_code == 204
    assert client.get("/api/subagents/web-research").status_code == 404


def test_skill_creator_route_installs_from_the_configured_source(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, object] = {}

    def fake_install(
        skills_dir: object, source: str, value: str, **kwargs: object
    ) -> dict[str, str]:
        seen.update({"source": source, "value": value, **kwargs})
        return {"name": "skill-creator"}

    monkeypatch.setattr(server, "install_skill", fake_install)

    response = client.post("/api/skills/install/skill-creator")

    assert response.status_code == 201
    assert response.json()["name"] == "skill-creator"
    assert seen["source"] == "git"
    assert seen["value"] == server.settings.harness_skill_creator_repo
    assert seen["subdir"] == server.settings.harness_skill_creator_subdir
    # La rotta statica non deve essere catturata da /api/skills/{name}.
    assert seen["by"] == "human"


def test_session_memory_is_seeded_from_the_template_then_diverges(client: TestClient) -> None:
    client.put("/api/memory", json={"content": "# Template\n"})
    session = client.post("/api/sessions", json={"title": "Memoria"}).json()

    # La sessione nasce con una copia del template.
    seeded = client.get(f"/api/sessions/{session['id']}/memory").json()["content"]
    assert "# Template" in seeded

    # Ciò che l'agente impara resta nella sessione e non tocca il template.
    client.put(
        f"/api/sessions/{session['id']}/memory",
        json={"content": "# Template\n\n## Apprendimenti\n- usare uv\n"},
    )
    assert client.get("/api/memory").json()["content"] == "# Template\n"
    assert "usare uv" in client.get(f"/api/sessions/{session['id']}/memory").json()["content"]


def test_promotion_is_explicit_and_copies_session_memory_into_the_template(
    client: TestClient,
) -> None:
    client.put("/api/memory", json={"content": "# Template\n"})
    session = client.post("/api/sessions", json={"title": "Memoria"}).json()
    client.put(f"/api/sessions/{session['id']}/memory", json={"content": "- usare uv\n"})

    response = client.post(f"/api/sessions/{session['id']}/memory/promote")

    assert response.status_code == 200
    assert client.get("/api/memory").json()["content"] == "- usare uv\n"


def test_promoting_an_empty_memory_is_refused(client: TestClient) -> None:
    session = client.post("/api/sessions", json={"title": "Vuota"}).json()
    client.put(f"/api/sessions/{session['id']}/memory", json={"content": "   \n"})

    assert client.post(f"/api/sessions/{session['id']}/memory/promote").status_code == 422


def _upload(client: TestClient, session_id: str, name: str, data: bytes) -> None:
    response = client.post(
        f"/api/sessions/{session_id}/files",
        files={"file": (name, data, "application/octet-stream")},
    )
    assert response.status_code == 201, response.text


def test_preview_serves_images_inline_with_a_type_it_chose_itself(client: TestClient) -> None:
    session = client.post("/api/sessions", json={"title": "Anteprima"}).json()
    _upload(client, session["id"], "grafico.png", b"\x89PNG\r\n\x1a\n fake")

    response = client.get(f"/api/sessions/{session['id']}/preview/grafico.png")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.headers["content-disposition"] == "inline"
    assert response.headers["x-content-type-options"] == "nosniff"


def test_preview_refuses_svg_and_html_because_they_are_executable_documents(
    client: TestClient,
) -> None:
    session = client.post("/api/sessions", json={"title": "Anteprima"}).json()
    _upload(client, session["id"], "x.svg", b"<svg onload='alert(1)'></svg>")
    _upload(client, session["id"], "x.html", b"<script>alert(1)</script>")

    for name in ("x.svg", "x.html"):
        response = client.get(f"/api/sessions/{session['id']}/preview/{name}")
        assert response.status_code == 415, name


def test_download_forces_attachment_even_for_html(client: TestClient) -> None:
    session = client.post("/api/sessions", json={"title": "Anteprima"}).json()
    _upload(client, session["id"], "x.html", b"<script>alert(1)</script>")

    response = client.get(f"/api/sessions/{session['id']}/files/x.html")

    assert response.status_code == 200
    assert "attachment" in response.headers["content-disposition"]


def test_preview_does_not_escape_the_workspace(client: TestClient) -> None:
    """Testato sulla guardia, non via HTTP: il client normalizza `../` prima di inviare."""
    session = client.post("/api/sessions", json={"title": "Anteprima"}).json()

    with pytest.raises(HTTPException) as excinfo:
        server._safe_workspace_path(session["id"], "../../control.sqlite")

    assert excinfo.value.status_code == 400


def test_cron_preview_translates_and_projects_in_the_chosen_timezone(client: TestClient) -> None:
    response = client.post(
        "/api/triggers/preview",
        json={"cron_expr": "0 9 * * *", "timezone": "Europe/Rome"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["description"] == "Ogni giorno alle 09:00 (fuso Europe/Rome)"
    assert len(payload["next_runs"]) == 3
    assert all("T09:00" in run for run in payload["next_runs"])


def test_cron_preview_rejects_an_unknown_timezone(client: TestClient) -> None:
    response = client.post(
        "/api/triggers/preview",
        json={"cron_expr": "0 9 * * *", "timezone": "Marte/Olympus"},
    )

    assert response.status_code == 422


def test_trigger_stores_timezone_and_exit_criteria(client: TestClient) -> None:
    response = client.post(
        "/api/triggers",
        json={
            "kind": "cron",
            "name": "Report",
            "goal_template": "Scrivi il report giornaliero.",
            "cron_expr": "0 9 * * *",
            "timezone": "Europe/Rome",
            "success_criteria": "Il file output/report.md esiste e cita la data di oggi.",
        },
    )

    assert response.status_code == 201
    trigger = response.json()
    assert trigger["timezone"] == "Europe/Rome"
    assert "output/report.md" in trigger["success_criteria"]

    # Il criterio finisce nel goal del run, come sezione dedicata.
    goal = server._trigger_goal(trigger)
    assert "Criterio di successo" in goal
    assert "output/report.md" in goal


def test_sessions_and_files_are_isolated(client: TestClient) -> None:
    first = client.post("/api/sessions", json={"title": "Prima"}).json()
    second = client.post("/api/sessions", json={"title": "Seconda"}).json()

    upload = client.post(
        f"/api/sessions/{first['id']}/files",
        files={"file": ("notes.txt", b"private", "text/plain")},
    )

    assert upload.status_code == 201
    first_files = client.get(f"/api/sessions/{first['id']}").json()["files"]
    assert [item["name"] for item in first_files] == ["notes.txt"]
    assert client.get(f"/api/sessions/{second['id']}").json()["files"] == []


def test_upload_blocks_traversal_and_unsupported_extension(client: TestClient) -> None:
    session = client.post("/api/sessions", json={}).json()

    response = client.post(
        f"/api/sessions/{session['id']}/files",
        files={"file": ("payload.exe", b"nope", "application/octet-stream")},
    )

    assert response.status_code == 400


def test_auto_approve_toggle_persists(client: TestClient) -> None:
    session = client.post("/api/sessions", json={}).json()
    assert session["auto_approve"] is False

    enabled = client.patch(f"/api/sessions/{session['id']}/auto-approve", json={"enabled": True})
    assert enabled.status_code == 200
    assert enabled.json()["auto_approve"] is True

    refetched = client.get(f"/api/sessions/{session['id']}").json()
    assert refetched["auto_approve"] is True

    disabled = client.patch(f"/api/sessions/{session['id']}/auto-approve", json={"enabled": False})
    assert disabled.json()["auto_approve"] is False


def test_auto_approve_missing_session_is_404(client: TestClient) -> None:
    response = client.patch(
        "/api/sessions/11111111-1111-1111-1111-111111111111/auto-approve",
        json={"enabled": True},
    )
    assert response.status_code == 404


def test_status_reports_on_demand_network(client: TestClient) -> None:
    payload = client.get("/api/status").json()
    assert payload["sandbox"]["network"] != "disabled"
    assert "on-demand" in payload["sandbox"]["network"]


def test_submit_action_without_pending_is_409(client: TestClient) -> None:
    session = client.post("/api/sessions", json={}).json()
    run = server.store.create_run(session["id"])
    response = client.post(f"/api/runs/{run['id']}/action", json={"response": "x"})
    assert response.status_code == 409


def test_select_attachments_prefers_output_dir() -> None:
    changed = ["scripts/fetch.py", "output/report.md", "notes.txt", "output/data.csv"]
    assert server._select_attachments(changed) == ["output/report.md", "output/data.csv"]


def test_select_attachments_falls_back_and_caps() -> None:
    changed = [f"file_{i}.txt" for i in range(30)]
    selected = server._select_attachments(changed)
    assert selected == changed[:20]


def test_pending_with_network_detects_flag_in_action_requests() -> None:
    # Forma reale del payload di interrupt: with_network annidato negli args.
    payload = {
        "action_requests": [
            {"action": "docker_exec", "args": {"command": "pip install x", "with_network": True}}
        ]
    }
    assert payload_wants_network(payload) is True


def test_pending_with_network_false_for_plain_exec() -> None:
    payload = {
        "action_requests": [
            {"action": "docker_exec", "args": {"command": "pytest", "with_network": False}}
        ]
    }
    assert payload_wants_network(payload) is False
    assert payload_wants_network({}) is False


def test_chat_rejects_empty_message(client: TestClient) -> None:
    session = client.post("/api/sessions", json={}).json()
    response = client.post(
        f"/api/sessions/{session['id']}/messages",
        json={"content": ""},
    )

    assert response.status_code == 422


def test_event_history_endpoint_pages_actions_without_deltas(client: TestClient) -> None:
    session = client.post("/api/sessions", json={}).json()
    run = server.store.create_run(session["id"])
    for index in range(14):
        event_type = "assistant.delta" if index % 4 == 0 else "tool.started"
        server.store.add_event(run["id"], session["id"], event_type, {"n": index})

    first = client.get(
        f"/api/runs/{run['id']}/event-history", params={"limit": 5}
    ).json()
    assert first["has_more_before"] is True
    assert len(first["events"]) == 5
    assert all(event["type"] == "tool.started" for event in first["events"])

    second = client.get(
        f"/api/runs/{run['id']}/event-history",
        params={"limit": 5, "before": first["events"][0]["id"]},
    ).json()
    assert second["events"][-1]["id"] < first["events"][0]["id"]


def test_session_reload_keeps_active_routing_and_tools(client: TestClient) -> None:
    session = client.post("/api/sessions", json={}).json()
    run = server.store.create_run(session["id"])
    server.store.update_run(run["id"], status="running")
    for event_type in (
        "subagent.routing.started",
        "assistant.delta",
        "subagent.routing.completed",
        "subagent.started",
        "subagent.tool.started",
        "tool.started",
    ):
        server.store.add_event(run["id"], session["id"], event_type, {"tool": "search"})

    reloaded = client.get(f"/api/sessions/{session['id']}").json()

    assert reloaded["latest_run"]["status"] == "running"
    assert [event["type"] for event in reloaded["events"]] == [
        "subagent.routing.started",
        "subagent.routing.completed",
        "subagent.started",
        "subagent.tool.started",
        "tool.started",
    ]
    assert reloaded["events_has_more_before"] is False


def test_sse_uses_generic_messages_for_unknown_event_types(client: TestClient) -> None:
    session = client.post("/api/sessions", json={}).json()
    run = server.store.create_run(session["id"])
    server.store.add_event(run["id"], session["id"], "future.telemetry", {"ok": True})
    server.store.update_run(run["id"], status="completed")

    with client.stream("GET", f"/api/runs/{run['id']}/events") as response:
        body = "".join(response.iter_text())

    assert '"type": "future.telemetry"' in body
    assert "event: future.telemetry" not in body
    assert "data:" in body


def test_stream_delta_buffer_groups_fragments() -> None:
    buffer = server.StreamDeltaBuffer(max_chars=5, max_interval_seconds=10)

    assert buffer.offer("ab", now=0) is None
    assert buffer.offer("cd", now=0) is None
    assert buffer.offer("e", now=0) == "abcde"
    assert buffer.offer("z", now=0) is None
    assert buffer.flush(now=1) == "z"


def test_state_changes_reject_unknown_browser_origin(client: TestClient) -> None:
    response = client.post(
        "/api/sessions",
        json={},
        headers={"Origin": "https://attacker.example"},
    )

    assert response.status_code == 403


def test_context_breakdown_identifies_workspace_file_output() -> None:
    messages = [
        AIMessage(
            content="",
            tool_calls=[
                {
                    "id": "call-1",
                    "name": "read_file",
                    "args": {"file_path": "/workspace/input.txt"},
                }
            ],
        ),
        ToolMessage(content="contenuto file", tool_call_id="call-1", name="read_file"),
    ]

    categories = {item["name"]: item for item in context_categories(messages)}

    assert categories["File letti"]["tokens"] > 0


def test_attachment_manifest_lists_workspace_files(client: TestClient) -> None:
    session = client.post("/api/sessions", json={}).json()
    client.post(
        f"/api/sessions/{session['id']}/files",
        files={"file": ("notes.txt", b"contenuto", "text/plain")},
    )

    manifest = server._attachment_manifest(session["id"])

    assert "/workspace/notes.txt" in manifest
    assert "TXT" in manifest


def test_attachment_manifest_empty_without_files(client: TestClient) -> None:
    session = client.post("/api/sessions", json={}).json()

    assert server._attachment_manifest(session["id"]) == ""


def test_context_endpoint_includes_system_and_memory(client: TestClient) -> None:
    session = client.post("/api/sessions", json={}).json()

    context = client.get(f"/api/sessions/{session['id']}/context").json()

    assert context["total_tokens"] > 0
    kinds = {entry["kind"] for entry in context["entries"]}
    assert "system" in kinds
    assert any(cat["name"] == "System & memoria" for cat in context["categories"])


def test_status_exposes_loop_features(client: TestClient) -> None:
    payload = client.get("/api/status").json()

    assert "verification" in payload and "enabled" in payload["verification"]
    assert "triggers" in payload and "enabled" in payload["triggers"]
    assert "overrides" in payload


def test_scheduler_toggle_persists_and_reports_state(client: TestClient) -> None:
    enabled = client.put("/api/settings/triggers", json={"enabled": True})
    assert enabled.status_code == 200
    assert enabled.json()["enabled"] is True
    # Persistito negli override: si ritrova alla lettura successiva della configurazione.
    assert server.settings.harness_enable_triggers is True

    disabled = client.put("/api/settings/triggers", json={"enabled": False})
    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False
    assert server.settings.harness_enable_triggers is False


def test_classify_run_error_gives_actionable_messages() -> None:
    invalid_file = server._classify_run_error(
        Exception(
            "Error code: 400 - {'message': 'file is badly formatted or corrupted', "
            "'code': 'invalid_file'}"
        )
    )
    assert "nuova sessione" in invalid_file and "corrotto" in invalid_file
    assert "frequenza" in server._classify_run_error(Exception("429 rate limit exceeded"))
    assert "chiave API" in server._classify_run_error(Exception("401 invalid api key"))
    # Errore ignoto: resta il messaggio generico.
    assert "fallita" in server._classify_run_error(Exception("qualcosa di strano"))


def test_classify_transient_provider_error_keeps_request_id() -> None:
    api_error = type("APIError", (Exception,), {})
    message = server._classify_run_error(
        api_error("Retry your request. Request ID req_visible123")
    )

    assert "temporaneo" in message
    assert "req_visible123" in message


def test_trigger_auto_approve_persisted_and_applied_to_session(client: TestClient) -> None:
    trigger = client.post(
        "/api/triggers",
        json={
            "kind": "cron",
            "name": "Autonomo",
            "goal_template": "fai",
            "cron_expr": "0 9 * * *",
            "auto_approve": True,
        },
    ).json()
    assert trigger["auto_approve"] is True

    # Al fire, la sessione del trigger deve ereditare l'auto-approvazione.
    session_id = server._ensure_trigger_session(server.store.get_trigger(trigger["id"]))
    assert server.store.get_session(session_id).get("auto_approve") is True

    # Un trigger di default richiede conferma.
    plain = client.post(
        "/api/triggers",
        json={"kind": "cron", "name": "Prudente", "goal_template": "x", "cron_expr": "0 9 * * *"},
    ).json()
    assert plain["auto_approve"] is False
    sid = server._ensure_trigger_session(server.store.get_trigger(plain["id"]))
    assert server.store.get_session(sid).get("auto_approve") is False


def test_webhook_fires_use_a_fresh_session_each_time(client: TestClient) -> None:
    trigger = client.post(
        "/api/triggers",
        json={"kind": "webhook", "name": "recensioni", "goal_template": "analizza"},
    ).json()
    t = server.store.get_trigger(trigger["id"])
    first = server._ensure_trigger_session(t)
    second = server._ensure_trigger_session(server.store.get_trigger(trigger["id"]))
    # Ogni evento webhook = sessione nuova: due invii non si accodano (niente skip).
    assert first != second


def test_cron_reuses_its_session(client: TestClient) -> None:
    trigger = client.post(
        "/api/triggers",
        json={"kind": "cron", "name": "orario", "goal_template": "x", "cron_expr": "0 9 * * *"},
    ).json()
    first = server._ensure_trigger_session(server.store.get_trigger(trigger["id"]))
    second = server._ensure_trigger_session(server.store.get_trigger(trigger["id"]))
    assert first == second


def test_text_response_trigger_injects_no_file_directive(client: TestClient) -> None:
    normal = client.post(
        "/api/triggers",
        json={"kind": "webhook", "name": "n", "goal_template": "classifica"},
    ).json()
    assert normal["text_response"] is False
    # Trigger normale: nessuna direttiva "risposta diretta" nel goal.
    goal_normal = server._trigger_goal(server.store.get_trigger(normal["id"]), {"x": 1})
    assert "risposta diretta" not in goal_normal.lower()

    direct = client.post(
        "/api/triggers",
        json={"kind": "webhook", "name": "d", "goal_template": "classifica", "text_response": True},
    ).json()
    assert direct["text_response"] is True
    goal_direct = server._trigger_goal(server.store.get_trigger(direct["id"]), {"x": 1})
    assert "risposta diretta" in goal_direct.lower()
    assert "non creare" in goal_direct.lower() and "docker_exec" in goal_direct.lower()


def test_trigger_model_tier_applied_to_session(client: TestClient) -> None:
    trigger = client.post(
        "/api/triggers",
        json={
            "kind": "cron",
            "name": "forte",
            "goal_template": "classifica",
            "cron_expr": "0 9 * * *",
            "model_tier": "high",
        },
    ).json()
    assert trigger["model_tier"] == "high"
    sid = server._ensure_trigger_session(server.store.get_trigger(trigger["id"]))
    assert server.store.get_session(sid).get("model_override") == "high"


def test_trigger_list_reports_running_state(client: TestClient) -> None:
    session = client.post("/api/sessions", json={"title": "Trig"}).json()
    trigger = client.post(
        "/api/triggers",
        json={"kind": "cron", "name": "Orario", "goal_template": "fai", "cron_expr": "0 9 * * *"},
    ).json()
    # Nessun run: non in esecuzione.
    got = next(t for t in client.get("/api/triggers").json() if t["id"] == trigger["id"])
    assert got["running"] is False

    # Aggancia la sessione al trigger e apri un run non terminale in quella sessione.
    server.store.attach_trigger_session(trigger["id"], session["id"])
    run = server.store.create_run(session["id"])
    server.store.update_run(run["id"], status="running")

    got = next(t for t in client.get("/api/triggers").json() if t["id"] == trigger["id"])
    assert got["running"] is True
    assert got["active_run_id"] == run["id"]


def test_costs_endpoint_aggregates_run_costs(client: TestClient) -> None:
    # Vuoto all'inizio.
    empty = client.get("/api/costs").json()
    assert empty["total_usd"] == "0" and empty["sessions"] == []

    # Simula due run con costo, come farebbe RunManager salvando usage con cost_usd.
    session = client.post("/api/sessions", json={"title": "Costosa"}).json()
    for cost in ("0.0030", "0.0020"):
        run = server.store.create_run(session["id"])
        server.store.update_run(run["id"], status="completed", usage={"cost_usd": cost})

    body = client.get("/api/costs").json()
    assert body["total_usd"] == "0.0050"
    assert body["sessions"][0]["session_id"] == session["id"]
    assert body["sessions"][0]["runs"] == 2
    assert len(body["recent"]) == 2


def test_estimate_cost_usd_uses_catalog() -> None:
    from agent_harness.pricing import catalog_from_settings, estimate_cost_usd

    settings = Settings(_env_file=None)
    catalog = catalog_from_settings(settings)
    # 1M token input + 1M output sul modello basso: costo = price_in + price_out.
    cost = estimate_cost_usd(
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        reasoning_tokens=0,
        provider="openai",
        model=settings.openai_model_low,
        catalog=catalog,
    )
    assert float(cost) > 0
    # Modello inesistente → nessun listino → costo 0.
    zero = estimate_cost_usd(
        input_tokens=1_000_000,
        output_tokens=0,
        reasoning_tokens=0,
        provider="openai",
        model="modello-che-non-esiste",
        catalog=catalog,
    )
    assert zero == "0"


def test_runtime_settings_roundtrip_and_range_validation(client: TestClient) -> None:
    fields = client.get("/api/settings/runtime").json()["fields"]
    keys = {f["key"] for f in fields}
    assert {"rubric_threshold", "max_tool_calls", "memory_max_chars"} <= keys

    # Valore valido: salvato e attivo (settings di processo aggiornato).
    ok = client.put("/api/settings/runtime", json={"values": {"max_tool_calls": 80}})
    assert ok.status_code == 200
    assert server.settings.harness_max_tool_calls == 80

    # Fuori range: rifiutato con 400, il valore non cambia.
    bad = client.put("/api/settings/runtime", json={"values": {"rubric_threshold": 5}})
    assert bad.status_code == 400
    assert server.settings.harness_max_tool_calls == 80


def test_rubric_endpoint_exposes_criteria_and_thresholds(client: TestClient) -> None:
    body = client.get("/api/rubric").json()
    assert "criteria" in body and len(body["criteria"]) == 4
    names = {c["name"] for c in body["criteria"]}
    assert {"completezza", "verifica", "aderenza", "sicurezza"} == names
    # I pesi sommano a 1 e le soglie ci sono.
    assert abs(sum(c["weight"] for c in body["criteria"]) - 1.0) < 1e-6
    assert body["safety_veto_below"] == 0.5
    assert 0 <= body["rubric_threshold"] <= 1


def test_notifications_lifecycle(client: TestClient) -> None:
    assert client.get("/api/notifications").json()["unread_count"] == 0
    # Simula ciò che fa RunManager quando un run termina.
    server.store.add_notification(type="run_completed", title="«Demo» — completato")
    server.store.add_notification(type="needs_approval", title="«Demo» — serve approvazione")
    body = client.get("/api/notifications").json()
    assert body["unread_count"] == 2
    assert len(body["notifications"]) == 2
    # Solo non lette.
    assert len(client.get("/api/notifications?unread=true").json()["notifications"]) == 2
    # Segna tutte lette.
    resp = client.post("/api/notifications/read", json={"ids": None})
    assert resp.json()["unread_count"] == 0
    assert client.get("/api/notifications?unread=true").json()["notifications"] == []


def test_pending_interrupts_endpoint_reflects_durable_store(client: TestClient) -> None:
    # Vuoto all'inizio.
    assert client.get("/api/durable/interrupts").json() == {"count": 0, "interrupts": []}
    # Un interrupt persistito (come farebbe RunManager) compare, e sopravvive a una rilettura.
    server.durable_store.record_interrupt(
        run_id="run-x", kind="approval", payload={"description": "Esecuzione comando sandbox"}
    )
    body = client.get("/api/durable/interrupts").json()
    assert body["count"] == 1
    assert body["interrupts"][0]["run_id"] == "run-x"
    assert body["interrupts"][0]["kind"] == "approval"
    assert "comando" in body["interrupts"][0]["description"]


def test_pdf_preview_has_no_blocking_csp_images_do(client: TestClient) -> None:
    session = client.post("/api/sessions", json={"title": "Preview"}).json()
    workspace = server.store.workspace_dir(session["id"])
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "doc.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
    (workspace / "img.png").write_bytes(b"\x89PNG\r\n\x1a\n")

    pdf = client.get(f"/api/sessions/{session['id']}/preview/doc.pdf")
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.headers["x-content-type-options"] == "nosniff"
    # La CSP restrittiva farebbe rifiutare il visualizzatore PDF del browser: niente CSP sul PDF.
    assert "content-security-policy" not in {k.lower() for k in pdf.headers}

    png = client.get(f"/api/sessions/{session['id']}/preview/img.png")
    assert png.status_code == 200
    # Le immagini mantengono la CSP di difesa in profondità.
    assert "content-security-policy" in {k.lower() for k in png.headers}


def test_text_preview_returns_content_and_kind(client: TestClient) -> None:
    session = client.post("/api/sessions", json={"title": "Text"}).json()
    workspace = server.store.workspace_dir(session["id"])
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "note.md").write_text("# Titolo\ntesto", encoding="utf-8")
    (workspace / "data.csv").write_text("a,b\n1,2", encoding="utf-8")
    (workspace / "script.py").write_text("print('ok')", encoding="utf-8")

    md = client.get(f"/api/sessions/{session['id']}/preview-text/note.md").json()
    assert md["kind"] == "markdown"
    assert "# Titolo" in md["content"]
    assert md["truncated"] is False

    csv = client.get(f"/api/sessions/{session['id']}/preview-text/data.csv").json()
    assert csv["kind"] == "csv"

    py = client.get(f"/api/sessions/{session['id']}/preview-text/script.py").json()
    assert py["kind"] == "text"

    # I documenti attivi restano esclusi dall'anteprima testuale.
    (workspace / "page.html").write_text("<script>alert(1)</script>", encoding="utf-8")
    blocked = client.get(f"/api/sessions/{session['id']}/preview-text/page.html")
    assert blocked.status_code == 415


def test_compact_context_requires_valid_config(client: TestClient) -> None:
    # La fixture non ha chiave OpenAI: il run parte ma fallisce alla validazione provider,
    # quindi qui verifichiamo che l'endpoint esista e restituisca un run_id (202), non 404/405.
    session = client.post("/api/sessions", json={"title": "Compact"}).json()
    resp = client.post(f"/api/sessions/{session['id']}/context/compact")
    assert resp.status_code == 202
    assert "run_id" in resp.json()


def test_compaction_result_uses_tool_outcome_not_model_claim() -> None:
    result = RunResult(
        text="Contesto compattato.",
        iterations=1,
        completed=True,
        messages=[
            HumanMessage(content="compact"),
            ToolMessage(
                content="Nothing to compact yet — conversation is within the token budget.",
                tool_call_id="compact-1",
                name="compact_conversation",
            ),
            AIMessage(content="Contesto compattato."),
        ],
    )

    state = server._classify_compaction_result(result)

    assert state == "no_work"
    assert result.completed is False
    assert result.terminal_status == "no_work"
    assert result.text == "Contesto già compatto; nessuna riduzione necessaria."


def test_compaction_result_accepts_actual_summary() -> None:
    result = RunResult(
        text="ignored",
        iterations=1,
        completed=False,
        messages=[
            HumanMessage(content="compact"),
            ToolMessage(
                content="Conversation compacted. Summarized 42 messages into a concise summary.",
                tool_call_id="compact-2",
                name="compact_conversation",
            ),
        ],
    )

    assert server._classify_compaction_result(result) == "completed"
    assert result.completed is True
    assert result.text == "Contesto compattato."


def test_mcp_config_roundtrip_and_validation(client: TestClient) -> None:
    # Un JSON valido con un server stdio viene salvato e riletto.
    valid = client.put(
        "/api/settings/mcp",
        json={"content": '{"mcpServers": {"echo": {"command": "python"}}}'},
    )
    assert valid.status_code == 200
    assert "echo" in valid.json()["servers"]
    assert "echo" in client.get("/api/settings/mcp").json()["content"]

    # Un server senza command/url viene rifiutato con 422 e non sovrascrive quello valido.
    broken = client.put(
        "/api/settings/mcp",
        json={"content": '{"mcpServers": {"bad": {}}}'},
    )
    assert broken.status_code == 422
    assert "echo" in client.get("/api/settings/mcp").json()["content"]


def test_improvements_list_empty_and_run_requires_key(client: TestClient) -> None:
    assert client.get("/api/improvements").json() == []

    response = client.post("/api/improve", json={"since": 100})

    assert response.status_code == 400


def test_apply_missing_improvement_is_404(client: TestClient) -> None:
    response = client.post(
        "/api/improvements/nope.md/apply",
        json={"mode": "canary", "fraction": 0.2},
    )

    assert response.status_code == 404


def test_unevaluated_improvement_cannot_be_promoted(client: TestClient) -> None:
    proposal = write_proposal(
        Proposal(harness_max_tool_calls=20),
        "report",
        server.settings.state_dir / "improvements",
    )

    response = client.post(
        f"/api/improvements/{proposal.name}/apply",
        json={"mode": "full", "fraction": 0.2},
    )

    assert response.status_code == 409
    assert "non valutata" in response.json()["detail"]


def test_full_promotion_waits_for_live_canary_gate(client: TestClient) -> None:
    proposal = write_proposal(
        Proposal(harness_max_tool_calls=20),
        "report",
        server.settings.state_dir / "improvements",
    )
    (server.settings.state_dir / "canary.json").write_text(
        json.dumps(
            {
                "source": proposal.name,
                "created_at": "2026-01-01T00:00:00+00:00",
                "fraction": 0.2,
                "baseline_fingerprint": "base",
                "candidate_fingerprint": "candidate",
                "overrides": {"harness_max_tool_calls": 20},
            }
        ),
        encoding="utf-8",
    )

    response = client.post(
        f"/api/improvements/{proposal.name}/apply",
        json={"mode": "full", "fraction": 0.2},
    )

    assert response.status_code == 409
    assert "Canary live non pronta" in response.json()["detail"]


def test_config_versions_and_canary_start_empty(client: TestClient) -> None:
    assert client.get("/api/config/versions").json() == []
    assert client.get("/api/status").json()["canary"] is None
    assert client.get("/api/canary/status").json()["status"] == "inactive"
    assert client.delete("/api/canary").status_code == 204


def test_clear_overrides_is_idempotent(client: TestClient) -> None:
    response = client.delete("/api/overrides")

    assert response.status_code == 204


def test_skills_crud_and_validation(client: TestClient) -> None:
    assert client.get("/api/skills").json() == []

    created = client.post(
        "/api/skills",
        json={
            "name": "data-analysis",
            "description": "Analizza CSV e produce statistiche. Usala per i dati.",
            "body": "# Analisi\n1. Leggi il CSV.",
        },
    )
    assert created.status_code == 201
    assert created.json()["valid"] is True

    assert {s["name"] for s in client.get("/api/skills").json()} == {"data-analysis"}
    assert client.get("/api/skills/data-analysis").json()["description"].startswith("Analizza")

    duplicate = client.post(
        "/api/skills",
        json={"name": "data-analysis", "description": "altra descrizione valida"},
    )
    assert duplicate.status_code == 409

    invalid = client.post(
        "/api/skills",
        json={"name": "Bad Name", "description": "descrizione valida abbastanza"},
    )
    assert invalid.status_code == 422

    assert client.delete("/api/skills/data-analysis").status_code == 204
    assert client.get("/api/skills").json() == []


def test_cron_trigger_rejects_invalid_expression(client: TestClient) -> None:
    response = client.post(
        "/api/triggers",
        json={"kind": "cron", "name": "c", "goal_template": "fai", "cron_expr": "nope"},
    )

    assert response.status_code == 422


def test_webhook_trigger_requires_valid_token(client: TestClient) -> None:
    trigger = client.post(
        "/api/triggers",
        json={"kind": "webhook", "name": "wh", "goal_template": "elabora l'evento"},
    ).json()
    assert trigger["token"]

    bad = client.post(
        f"/api/triggers/{trigger['id']}/webhook",
        headers={"X-Trigger-Token": "sbagliato"},
        json={"payload": 1},
    )
    assert bad.status_code == 403

    ok = client.post(
        f"/api/triggers/{trigger['id']}/webhook",
        headers={"X-Trigger-Token": trigger["token"]},
        json={"payload": 1},
    )
    assert ok.status_code == 202
    assert ok.json()["run_id"]


def test_webhook_synchronous_wait_returns_final_status(client: TestClient) -> None:
    trigger = client.post(
        "/api/triggers",
        json={"kind": "webhook", "name": "sync", "goal_template": "elabora", "auto_approve": True},
    ).json()
    # Senza chiave il run fallisce subito, ma il path sincrono deve comunque ATTENDERE il run
    # e rispondere 200 con lo stato finale e il campo response (invece del 202 fire-and-forget).
    resp = client.post(
        f"/api/triggers/{trigger['id']}/webhook?token={trigger['token']}&wait=true&timeout=30",
        json={"x": 1},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "status" in body and "response" in body and body["run_id"]


def test_webhook_accepts_token_in_query_and_text_body(client: TestClient) -> None:
    # Percorso "pagina browser": token nel query, body text/plain (nessun preflight).
    trigger = client.post(
        "/api/triggers",
        json={"kind": "webhook", "name": "wh2", "goal_template": "analizza la recensione"},
    ).json()
    resp = client.post(
        f"/api/triggers/{trigger['id']}/webhook?token={trigger['token']}",
        headers={"Content-Type": "text/plain;charset=UTF-8"},
        content='{"cliente":"Anna","rating":4,"testo":"ottimo"}',
    )
    assert resp.status_code == 202
    assert resp.json()["run_id"]
    assert resp.headers.get("access-control-allow-origin") == "*"

    # Query token errato → 403.
    bad = client.post(
        f"/api/triggers/{trigger['id']}/webhook?token=sbagliato",
        headers={"Content-Type": "text/plain"},
        content="{}",
    )
    assert bad.status_code == 403


def test_stop_sandbox_missing_session_is_404(client: TestClient) -> None:
    response = client.post("/api/sessions/11111111-1111-1111-1111-111111111111/sandbox/stop")
    assert response.status_code == 404


def test_stop_sandbox_rejects_while_run_busy(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = client.post("/api/sessions", json={}).json()
    run = server.store.create_run(session["id"])
    server.store.update_run(run["id"], status="running")

    response = client.post(f"/api/sessions/{session['id']}/sandbox/stop")

    assert response.status_code == 409


def test_stop_sandbox_calls_manager_when_idle(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = client.post("/api/sessions", json={}).json()
    stopped: list[str] = []
    monkeypatch.setattr(server.session_sandbox_manager, "stop", stopped.append)

    response = client.post(f"/api/sessions/{session['id']}/sandbox/stop")

    assert response.status_code == 202
    assert stopped == [session["id"]]


def test_delete_session_removes_scoped_workspace(client: TestClient) -> None:
    session = client.post("/api/sessions", json={}).json()
    workspace = server.store.workspace_dir(session["id"])

    response = client.delete(f"/api/sessions/{session['id']}")

    assert response.status_code == 204
    assert not workspace.exists()


def test_provider_settings_get_hides_keys(client: TestClient) -> None:
    body = client.get("/api/settings/providers").json()
    assert {p["name"] for p in body["providers"]} == {"openai", "anthropic", "ollama", "mlx"}
    assert [t["tier"] for t in body["tiers"]] == ["low", "mid", "high"]
    openai = next(p for p in body["providers"] if p["name"] == "openai")
    assert openai["key_configured"] is False  # fixture: openai_api_key=None
    assert "sk-" not in str(body)


def test_provider_settings_set_key_and_status_reflects(client: TestClient) -> None:
    resp = client.put("/api/settings/providers", json={"openai_api_key": "sk-live"})
    assert resp.status_code == 200
    openai = next(p for p in resp.json()["providers"] if p["name"] == "openai")
    assert openai["key_configured"] is True
    # Persistito e riletto: la chiave resta configurata.
    again = client.get("/api/settings/providers").json()
    assert next(p for p in again["providers"] if p["name"] == "openai")["key_configured"] is True


def test_provider_settings_assign_local_tiers_without_key(client: TestClient) -> None:
    resp = client.put(
        "/api/settings/providers",
        json={
            "tiers": [
                {"tier": "low", "provider": "ollama", "model": "qwen3:8b"},
                {"tier": "mid", "provider": "ollama", "model": "qwen3:14b"},
                {"tier": "high", "provider": "ollama", "model": "qwen3:14b"},
            ]
        },
    )
    assert resp.status_code == 200
    tiers = {t["tier"]: t for t in resp.json()["tiers"]}
    assert tiers["low"]["provider"] == "ollama"
    assert tiers["low"]["model"] == "qwen3:8b"
    # Lo status runtime riflette il provider del gradino.
    models = {m["tier"]: m for m in client.get("/api/status").json()["models"]}
    assert models["low"]["provider"] == "ollama"


def test_provider_settings_cloud_tier_without_key_is_rejected(client: TestClient) -> None:
    resp = client.put(
        "/api/settings/providers",
        json={"tiers": [{"tier": "high", "provider": "anthropic", "model": "claude-opus-4-8"}]},
    )
    assert resp.status_code == 400
    assert "chiave" in resp.json()["detail"].lower()


def test_local_models_endpoint(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_list(_settings: object, provider: str) -> dict[str, object]:
        if provider == "ollama":
            return {"running": True, "models": ["qwen3:8b", "gemma3:4b"]}
        return {"running": False, "models": []}

    monkeypatch.setattr(server.provider_cfg, "list_local_models", fake_list)
    body = client.get("/api/settings/providers/ollama/models").json()
    assert body["running"] is True
    assert "qwen3:8b" in body["models"]
    # Provider non locale → non in esecuzione, lista vuota.
    off = client.get("/api/settings/providers/mlx/models").json()
    assert off == {"running": False, "models": []}


def test_provider_settings_toggle_lean_flags(client: TestClient) -> None:
    # Base valida (gradini locali, nessuna chiave richiesta), poi snellisce i flag.
    resp = client.put(
        "/api/settings/providers",
        json={
            "tiers": [
                {"tier": "low", "provider": "ollama", "model": "qwen3:8b"},
                {"tier": "mid", "provider": "ollama", "model": "qwen3:8b"},
                {"tier": "high", "provider": "ollama", "model": "qwen3:8b"},
            ],
            "flags": {"web_search": False, "browser": False, "mcp": False, "rubric": False},
        },
    )
    assert resp.status_code == 200
    flags = resp.json()["flags"]
    assert flags == {"web_search": False, "browser": False, "mcp": False, "rubric": False}
    # Persistito: riletto resta spento.
    again = client.get("/api/settings/providers").json()["flags"]
    assert again["rubric"] is False
    # Lo status runtime riflette il grader spento.
    assert client.get("/api/status").json()["verification"]["enabled"] is False
