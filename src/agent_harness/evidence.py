from __future__ import annotations

import hashlib
import json
import platform
import re
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

SCHEMA_VERSION = 1
_TERMINAL_STATUSES = {
    "completed",
    "incomplete",
    "blocked_needs_human",
    "failed_verification",
    "budget_exceeded",
    "security_stop",
    "no_work",
    "failed",
    "cancelled",
}
_EXIT_CODE = re.compile(r"\bexit_code\s*=\s*(-?\d+)\b", re.IGNORECASE)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _canonical_json(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _package_version() -> str:
    try:
        return version("langchain-agent-harness")
    except PackageNotFoundError:
        return "development"


class EvidenceRequirement(BaseModel):
    id: str
    label: str
    required: bool = True
    passed: bool
    detail: str = ""


class ArtifactEvidence(BaseModel):
    path: str
    sha256: str
    size: int = Field(ge=0)


class CommandEvidence(BaseModel):
    tool: str
    tool_call_id: str = ""
    arguments: str = ""
    arguments_sha256: str = ""
    result: str = ""
    output_sha256: str = ""
    exit_code: int | None = None
    elapsed_ms: int | None = None
    passed: bool


class VerifierEvidence(BaseModel):
    kind: str
    passed: bool
    score: float | None = None
    event_id: int | None = None
    summary: str = ""


class EvidenceContract(BaseModel):
    task_kind: str
    passed: bool
    requirements: list[EvidenceRequirement]


class EvidenceManifest(BaseModel):
    schema_version: int = SCHEMA_VERSION
    run_id: str
    session_id: str
    created_at: str
    terminal_status: str
    input_sha256: str
    output_sha256: str
    environment: dict[str, str]
    contract: EvidenceContract
    artifacts: list[ArtifactEvidence]
    commands: list[CommandEvidence]
    verifiers: list[VerifierEvidence]
    manifest_sha256: str = ""


class IntegrityCheck(BaseModel):
    id: str
    passed: bool
    detail: str


class EvidenceIntegrity(BaseModel):
    valid: bool
    checked_at: str
    checks: list[IntegrityCheck]


def _artifact_evidence(
    workspace: Path, paths: list[str]
) -> tuple[list[ArtifactEvidence], list[str]]:
    root = workspace.resolve()
    artifacts: list[ArtifactEvidence] = []
    missing: list[str] = []
    for relative_name in sorted(dict.fromkeys(paths)):
        candidate = (root / relative_name).resolve()
        if (
            not candidate.is_relative_to(root)
            or candidate == root
            or not candidate.is_file()
            or candidate.is_symlink()
        ):
            missing.append(relative_name)
            continue
        try:
            content = candidate.read_bytes()
        except OSError:
            missing.append(relative_name)
            continue
        artifacts.append(
            ArtifactEvidence(
                path=relative_name,
                sha256=_sha256_bytes(content),
                size=len(content),
            )
        )
    return artifacts, missing


def _command_evidence(events: list[dict[str, Any]]) -> list[CommandEvidence]:
    started: dict[str, dict[str, Any]] = {}
    commands: list[CommandEvidence] = []
    for event in events:
        payload = event.get("payload")
        if not isinstance(payload, dict):
            continue
        event_type = str(event.get("type", ""))
        call_id = str(payload.get("tool_call_id", ""))
        if event_type in {"tool.started", "subagent.tool.started"} and call_id:
            started[call_id] = payload
            continue
        if event_type not in {
            "tool.completed",
            "tool.failed",
            "subagent.tool.completed",
            "subagent.tool.failed",
        }:
            continue
        output = str(payload.get("output", ""))
        arguments = str(started.get(call_id, {}).get("args", ""))
        exit_match = _EXIT_CODE.search(output)
        exit_code = int(exit_match.group(1)) if exit_match else None
        tool = str(payload.get("tool", "tool"))
        completed = event_type.endswith(".completed")
        passed = completed and (
            exit_code == 0 if tool == "docker_exec" else exit_code is None or exit_code == 0
        )
        commands.append(
            CommandEvidence(
                tool=tool,
                tool_call_id=call_id,
                arguments=arguments,
                arguments_sha256=_sha256_text(arguments) if arguments else "",
                result=output,
                output_sha256=_sha256_text(output) if output else "",
                exit_code=exit_code,
                elapsed_ms=(
                    int(payload["elapsed_ms"])
                    if isinstance(payload.get("elapsed_ms"), int)
                    else None
                ),
                passed=passed,
            )
        )
    return commands


def _verifier_evidence(events: list[dict[str, Any]]) -> list[VerifierEvidence]:
    result: list[VerifierEvidence] = []
    for event in events:
        payload = event.get("payload")
        if not isinstance(payload, dict):
            continue
        event_type = str(event.get("type", ""))
        if event_type == "grader.completed":
            result.append(
                VerifierEvidence(
                    kind="rubric",
                    passed=bool(payload.get("passed")),
                    score=(
                        float(payload["score"])
                        if isinstance(payload.get("score"), int | float)
                        else None
                    ),
                    event_id=int(event["id"]) if isinstance(event.get("id"), int) else None,
                    summary=str(payload.get("feedback", ""))[:500],
                )
            )
    return result


def build_evidence_manifest(
    *,
    run_id: str,
    session_id: str,
    goal: str,
    answer: str,
    terminal_status: str,
    workspace: Path,
    artifact_paths: list[str],
    events: list[dict[str, Any]],
    requires_runtime_verification: bool,
    created_at: str | None = None,
) -> EvidenceManifest:
    artifacts, missing_artifacts = _artifact_evidence(workspace, artifact_paths)
    commands = _command_evidence(events)
    sandbox_passed = any(command.tool == "docker_exec" and command.passed for command in commands)
    requirements = [
        EvidenceRequirement(
            id="terminal_outcome",
            label="Stato terminale persistito",
            passed=terminal_status in _TERMINAL_STATUSES,
            detail=terminal_status,
        ),
        EvidenceRequirement(
            id="assistant_response",
            label="Risultato del run registrato",
            passed=bool(answer.strip()) or terminal_status == "cancelled",
            detail="risposta presente" if answer.strip() else "nessuna risposta finale",
        ),
        EvidenceRequirement(
            id="runtime_verification",
            label="Verifica riproducibile in sandbox",
            required=requires_runtime_verification,
            passed=(not requires_runtime_verification) or sandbox_passed,
            detail=(
                "docker_exec completato con exit code 0"
                if sandbox_passed
                else "nessuna verifica sandbox riuscita"
            ),
        ),
        EvidenceRequirement(
            id="artifact_integrity",
            label="Hash degli artefatti prodotti",
            required=bool(artifact_paths),
            passed=not missing_artifacts and len(artifacts) == len(set(artifact_paths)),
            detail=(
                f"{len(artifacts)} artefatti acquisiti"
                if not missing_artifacts
                else "artefatti mancanti: " + ", ".join(missing_artifacts)
            ),
        ),
    ]
    required_passed = all(item.passed for item in requirements if item.required)
    manifest = EvidenceManifest(
        run_id=run_id,
        session_id=session_id,
        created_at=created_at or _utc_now(),
        terminal_status=terminal_status,
        input_sha256=_sha256_text(goal),
        output_sha256=_sha256_text(answer),
        environment={
            "harness_version": _package_version(),
            "python": platform.python_version(),
            "platform": platform.system().lower(),
        },
        contract=EvidenceContract(
            task_kind="workspace_mutation" if requires_runtime_verification else "general",
            passed=required_passed,
            requirements=requirements,
        ),
        artifacts=artifacts,
        commands=commands,
        verifiers=_verifier_evidence(events),
    )
    digest_payload = manifest.model_dump(mode="json", exclude={"manifest_sha256"})
    manifest.manifest_sha256 = _sha256_bytes(_canonical_json(digest_payload))
    return manifest


def verify_evidence_manifest(manifest: EvidenceManifest, workspace: Path) -> EvidenceIntegrity:
    digest_payload = manifest.model_dump(mode="json", exclude={"manifest_sha256"})
    computed_manifest_hash = _sha256_bytes(_canonical_json(digest_payload))
    checks = [
        IntegrityCheck(
            id="manifest",
            passed=computed_manifest_hash == manifest.manifest_sha256,
            detail=(
                "manifest invariato"
                if computed_manifest_hash == manifest.manifest_sha256
                else "hash del manifest non corrispondente"
            ),
        )
    ]
    root = workspace.resolve()
    for artifact in manifest.artifacts:
        candidate = (root / artifact.path).resolve()
        valid_path = candidate.is_relative_to(root) and candidate != root and candidate.is_file()
        try:
            content = candidate.read_bytes() if valid_path else b""
        except OSError:
            content = b""
            valid_path = False
        current_hash = _sha256_bytes(content) if valid_path else ""
        passed = valid_path and current_hash == artifact.sha256 and len(content) == artifact.size
        checks.append(
            IntegrityCheck(
                id=f"artifact:{artifact.path}",
                passed=passed,
                detail="integro" if passed else "mancante o modificato",
            )
        )
    return EvidenceIntegrity(
        valid=all(check.passed for check in checks),
        checked_at=_utc_now(),
        checks=checks,
    )
