from pathlib import Path

from agent_harness.evidence import build_evidence_manifest, verify_evidence_manifest


def test_manifest_hashes_artifacts_and_detects_tampering(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    artifact = workspace / "output.txt"
    artifact.write_text("risultato verificato", encoding="utf-8")
    events = [
        {
            "id": 1,
            "type": "tool.started",
            "payload": {
                "tool": "docker_exec",
                "tool_call_id": "call-1",
                "args": '{"command":"pytest -q"}',
            },
        },
        {
            "id": 2,
            "type": "tool.completed",
            "payload": {
                "tool": "docker_exec",
                "tool_call_id": "call-1",
                "output": "exit_code=0 STDOUT: 12 passed",
                "elapsed_ms": 42,
            },
        },
        {
            "id": 3,
            "type": "grader.completed",
            "payload": {"passed": True, "score": 0.96, "feedback": "Completo"},
        },
    ]

    manifest = build_evidence_manifest(
        run_id="run-1",
        session_id="session-1",
        goal="Crea output.txt",
        answer="Fatto",
        terminal_status="completed",
        workspace=workspace,
        artifact_paths=["output.txt"],
        events=events,
        requires_runtime_verification=True,
        created_at="2026-07-14T12:00:00+00:00",
    )

    assert manifest.contract.passed is True
    assert manifest.artifacts[0].sha256
    assert manifest.commands[0].exit_code == 0
    assert manifest.verifiers[0].passed is True
    assert verify_evidence_manifest(manifest, workspace).valid is True

    artifact.write_text("contenuto alterato", encoding="utf-8")
    integrity = verify_evidence_manifest(manifest, workspace)

    assert integrity.valid is False
    assert integrity.checks[-1].id == "artifact:output.txt"
    assert integrity.checks[-1].detail == "mancante o modificato"


def test_contract_fails_when_required_runtime_verification_is_missing(tmp_path: Path) -> None:
    manifest = build_evidence_manifest(
        run_id="run-2",
        session_id="session-1",
        goal="Scrivi un file",
        answer="Fatto",
        terminal_status="completed",
        workspace=tmp_path,
        artifact_paths=[],
        events=[],
        requires_runtime_verification=True,
    )

    assert manifest.contract.passed is False
    requirement = next(
        item for item in manifest.contract.requirements if item.id == "runtime_verification"
    )
    assert requirement.required is True
    assert requirement.passed is False


def test_docker_verification_requires_explicit_zero_exit_code(tmp_path: Path) -> None:
    manifest = build_evidence_manifest(
        run_id="run-3",
        session_id="session-1",
        goal="Crea un file",
        answer="Fatto",
        terminal_status="completed",
        workspace=tmp_path,
        artifact_paths=[],
        events=[
            {
                "id": 1,
                "type": "tool.completed",
                "payload": {
                    "tool": "docker_exec",
                    "tool_call_id": "ambiguous",
                    "output": "risultato non interpretabile",
                },
            }
        ],
        requires_runtime_verification=True,
    )

    assert manifest.commands[0].passed is False
    assert manifest.contract.passed is False
