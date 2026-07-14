import hashlib
import json
from pathlib import Path

from agent_harness.evidence import (
    EvidenceManifest,
    assess_delivery_readiness,
    build_evidence_manifest,
    create_evidence_bundle,
    run_independent_checker,
    verify_evidence_manifest,
)


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


def test_command_previews_redact_secrets_but_keep_raw_hashes(tmp_path: Path) -> None:
    manifest = build_evidence_manifest(
        run_id="run-redaction",
        session_id="session-1",
        goal="Analizza",
        answer="Fatto",
        terminal_status="completed",
        workspace=tmp_path,
        artifact_paths=[],
        events=[
            {
                "id": 1,
                "type": "tool.started",
                "payload": {
                    "tool": "http",
                    "tool_call_id": "secret-call",
                    "args": 'token="super-secret" authorization=Bearer abc.def',
                },
            },
            {
                "id": 2,
                "type": "tool.completed",
                "payload": {
                    "tool": "http",
                    "tool_call_id": "secret-call",
                    "output": "Bearer response-token",
                },
            },
        ],
        requires_runtime_verification=False,
    )

    command = manifest.commands[0]
    assert "super-secret" not in command.arguments
    assert "abc.def" not in command.arguments
    assert "response-token" not in command.result
    assert command.arguments_sha256
    assert command.output_sha256


def test_checker_uses_a_separate_read_only_snapshot(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    artifact = workspace / "output.txt"
    artifact.write_text("versione approvata", encoding="utf-8")
    manifest = build_evidence_manifest(
        run_id="run-checker",
        session_id="session-1",
        goal="Analizza output.txt",
        answer="Analisi completata",
        terminal_status="completed",
        workspace=workspace,
        artifact_paths=["output.txt"],
        events=[],
        requires_runtime_verification=False,
    )

    bundle = create_evidence_bundle(manifest, workspace, tmp_path / "evidence" / manifest.run_id)
    checker = run_independent_checker(bundle)

    assert checker.passed is True
    assert checker.read_only is True
    assert (bundle / "artifacts" / "output.txt").read_text() == "versione approvata"

    artifact.write_text("versione alterata", encoding="utf-8")
    assert verify_evidence_manifest(manifest, workspace).valid is False
    assert run_independent_checker(bundle).passed is True


def test_delivery_readiness_requires_ci_preview_clean_branch_and_human_gate(
    tmp_path: Path,
) -> None:
    manifest = build_evidence_manifest(
        run_id="run-delivery",
        session_id="session-1",
        goal="Prepara il deploy in produzione",
        answer="Pronto",
        terminal_status="completed",
        workspace=tmp_path,
        artifact_paths=[],
        events=[],
        requires_runtime_verification=False,
    )
    bundle = create_evidence_bundle(manifest, tmp_path, tmp_path / "bundle")
    checker = run_independent_checker(bundle)
    integrity = verify_evidence_manifest(manifest, tmp_path)
    gate = {
        "decision": "approved",
        "manifest_sha256": manifest.manifest_sha256,
        "decided_by": "tester",
    }

    delivery = assess_delivery_readiness(manifest, integrity, checker, gate)

    assert delivery.relevant is True
    assert delivery.ready is False
    checks = {check.id: check.passed for check in delivery.checks}
    assert checks["integrity"] is True
    assert checks["independent_checker"] is True
    assert checks["human_gate"] is True
    assert checks["ci_green"] is False
    assert checks["preview_environment"] is False


def test_schema_one_manifest_keeps_its_original_digest_contract(tmp_path: Path) -> None:
    current = build_evidence_manifest(
        run_id="legacy-run",
        session_id="session-1",
        goal="Analizza",
        answer="Fatto",
        terminal_status="completed",
        workspace=tmp_path,
        artifact_paths=[],
        events=[],
        requires_runtime_verification=False,
    )
    legacy = current.model_dump(mode="json", exclude={"manifest_sha256"})
    legacy["schema_version"] = 1
    legacy.pop("provenance")
    legacy.pop("delivery")
    encoded = json.dumps(
        legacy,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    legacy["manifest_sha256"] = hashlib.sha256(encoded).hexdigest()

    parsed = EvidenceManifest.model_validate(legacy)

    assert verify_evidence_manifest(parsed, tmp_path).valid is True
