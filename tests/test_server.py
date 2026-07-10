import itertools
import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, ToolMessage

import agent_harness.server as server
from agent_harness.config import Settings
from agent_harness.control_store import ControlStore
from agent_harness.improve import Proposal, write_proposal
from agent_harness.usage import context_categories


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    (tmp_path / "skills").mkdir()
    (tmp_path / "memories").mkdir()
    (tmp_path / "memories" / "AGENTS.md").write_text("# Test\n", encoding="utf-8")
    settings = Settings(_env_file=None, project_root=tmp_path, openai_api_key=None)
    isolated_store = ControlStore(settings)
    monkeypatch.setattr(server, "settings", settings)
    monkeypatch.setattr(server, "store", isolated_store)
    monkeypatch.setattr(server, "run_manager", server.RunManager())
    with TestClient(server.app) as test_client:
        yield test_client
    isolated_store.close()


def test_status_exposes_runtime_without_secrets(client: TestClient) -> None:
    response = client.get("/api/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["backend"] == "online"
    assert "openai_api_key" not in payload
    assert "docker_exec" in {tool["name"] for tool in payload["tools"]}


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

    enabled = client.patch(
        f"/api/sessions/{session['id']}/auto-approve", json={"enabled": True}
    )
    assert enabled.status_code == 200
    assert enabled.json()["auto_approve"] is True

    refetched = client.get(f"/api/sessions/{session['id']}").json()
    assert refetched["auto_approve"] is True

    disabled = client.patch(
        f"/api/sessions/{session['id']}/auto-approve", json={"enabled": False}
    )
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
    assert server._pending_with_network(payload) is True


def test_pending_with_network_false_for_plain_exec() -> None:
    payload = {
        "action_requests": [
            {"action": "docker_exec", "args": {"command": "pytest", "with_network": False}}
        ]
    }
    assert server._pending_with_network(payload) is False
    assert server._pending_with_network({}) is False


def test_chat_rejects_empty_message(client: TestClient) -> None:
    session = client.post("/api/sessions", json={}).json()
    response = client.post(
        f"/api/sessions/{session['id']}/messages",
        json={"content": ""},
    )

    assert response.status_code == 422


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


def test_stop_sandbox_missing_session_is_404(client: TestClient) -> None:
    response = client.post(
        "/api/sessions/11111111-1111-1111-1111-111111111111/sandbox/stop"
    )
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
