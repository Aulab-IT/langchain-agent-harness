from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, ToolMessage

import agent_harness.server as server
from agent_harness.config import Settings
from agent_harness.control_store import ControlStore


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

    categories = {item["name"]: item for item in server._context_categories(messages)}

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

    response = client.post("/api/improve", json={"since": 100, "apply": False})

    assert response.status_code == 400


def test_apply_missing_improvement_is_404(client: TestClient) -> None:
    response = client.post("/api/improvements/nope.md/apply")

    assert response.status_code == 404


def test_clear_overrides_is_idempotent(client: TestClient) -> None:
    response = client.delete("/api/overrides")

    assert response.status_code == 204


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


def test_delete_session_removes_scoped_workspace(client: TestClient) -> None:
    session = client.post("/api/sessions", json={}).json()
    workspace = server.store.workspace_dir(session["id"])

    response = client.delete(f"/api/sessions/{session['id']}")

    assert response.status_code == 204
    assert not workspace.exists()
