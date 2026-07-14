from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import tempfile
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, Field

SCHEMA_VERSION = 2
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
_SENSITIVE_VALUE = re.compile(
    r"(?i)(\b(?:api[_-]?key|token|secret|password|authorization)\b[\"']?\s*[:=]\s*)"
    r"([\"']?)([^\s,}\"']+)([\"']?)"
)
_BEARER_TOKEN = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]+=*")


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _redact_sensitive(value: str) -> str:
    redacted = _BEARER_TOKEN.sub("Bearer ***", value)
    return _SENSITIVE_VALUE.sub(r"\1\2***\4", redacted)


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


class SourceProvenance(BaseModel):
    repository: bool = False
    branch: str = ""
    commit: str = ""
    dirty: bool = False
    worktree_sha256: str = ""
    ci_provider: str = "local"
    ci_status: str = "local"
    ci_run_id: str = ""
    preview_url: str = ""


class DeliveryBoundary(BaseModel):
    relevant: bool = False
    requires_human_gate: bool = False
    rollback_plan: str = "Non applicabile: il run non esegue delivery."


class EvidenceManifest(BaseModel):
    schema_version: int = SCHEMA_VERSION
    run_id: str
    session_id: str
    created_at: str
    terminal_status: str
    input_sha256: str
    output_sha256: str
    environment: dict[str, str]
    provenance: SourceProvenance = Field(default_factory=SourceProvenance)
    delivery: DeliveryBoundary = Field(default_factory=DeliveryBoundary)
    contract: EvidenceContract
    artifacts: list[ArtifactEvidence]
    commands: list[CommandEvidence]
    verifiers: list[VerifierEvidence]
    manifest_sha256: str = ""


class IntegrityCheck(BaseModel):
    id: str
    passed: bool
    detail: str


class EvidenceCheckerResult(BaseModel):
    checker: str = "deterministic-read-only-v1"
    manifest_sha256: str
    checked_at: str
    read_only: bool
    passed: bool
    checks: list[IntegrityCheck]


class DeliveryReadiness(BaseModel):
    relevant: bool
    ready: bool
    checks: list[IntegrityCheck]


class EvidenceIntegrity(BaseModel):
    valid: bool
    checked_at: str
    checks: list[IntegrityCheck]


def _manifest_payload(manifest: EvidenceManifest) -> dict[str, Any]:
    payload = manifest.model_dump(mode="json", exclude={"manifest_sha256"})
    if manifest.schema_version < 2:
        payload.pop("provenance", None)
        payload.pop("delivery", None)
    return payload


def _git_value(project_root: Path, *arguments: str) -> str:
    try:
        result = subprocess.run(
            ["git", *arguments],
            cwd=project_root,
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def _safe_preview_url() -> str:
    raw = (os.getenv("DEPLOYMENT_URL") or os.getenv("VERCEL_URL") or "").strip()[:500]
    if raw and "://" not in raw:
        raw = f"https://{raw}"
    parsed = urlparse(raw)
    return raw if parsed.scheme in {"http", "https"} and parsed.netloc else ""


def collect_source_provenance(project_root: Path | None) -> SourceProvenance:
    if project_root is None:
        return SourceProvenance()
    root = project_root.resolve()
    commit = _git_value(root, "rev-parse", "HEAD")
    branch = _git_value(root, "branch", "--show-current")
    status_output = _git_value(root, "status", "--porcelain=v1")
    ci_provider = "github-actions" if os.getenv("GITHUB_ACTIONS") == "true" else "local"
    if os.getenv("GITLAB_CI") == "true":
        ci_provider = "gitlab-ci"
    ci_active = os.getenv("CI", "").lower() == "true"
    ci_status = (os.getenv("CI_JOB_STATUS") or ("running" if ci_active else "local"))[:40]
    ci_run_id = (os.getenv("GITHUB_RUN_ID") or os.getenv("CI_PIPELINE_ID") or "")[:120]
    return SourceProvenance(
        repository=bool(commit),
        branch=branch[:200],
        commit=commit[:64],
        dirty=bool(status_output),
        worktree_sha256=_sha256_text(str(root)),
        ci_provider=ci_provider,
        ci_status=ci_status,
        ci_run_id=ci_run_id,
        preview_url=_safe_preview_url(),
    )


_DELIVERY_INTENT = re.compile(
    r"\b(deploy|deployment|rilasci[ao]|pubblica|pubblicare|merge|pull request|"
    r"migrazion[ei]|migrate|rollback)\b",
    re.IGNORECASE,
)


def delivery_boundary(goal: str, provenance: SourceProvenance) -> DeliveryBoundary:
    relevant = bool(_DELIVERY_INTENT.search(goal))
    rollback = "Non applicabile: il run non esegue delivery."
    if relevant and provenance.commit:
        rollback = f"Ripristinare con git revert {provenance.commit}."
    elif relevant:
        rollback = "Ripristinare l'ultima versione approvata prima di qualunque deploy."
    return DeliveryBoundary(
        relevant=relevant,
        requires_human_gate=relevant,
        rollback_plan=rollback,
    )


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
                arguments=_redact_sensitive(arguments),
                arguments_sha256=_sha256_text(arguments) if arguments else "",
                result=_redact_sensitive(output),
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
    project_root: Path | None = None,
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
    provenance = collect_source_provenance(project_root)
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
        provenance=provenance,
        delivery=delivery_boundary(goal, provenance),
        contract=EvidenceContract(
            task_kind="workspace_mutation" if requires_runtime_verification else "general",
            passed=required_passed,
            requirements=requirements,
        ),
        artifacts=artifacts,
        commands=commands,
        verifiers=_verifier_evidence(events),
    )
    manifest.manifest_sha256 = _sha256_bytes(_canonical_json(_manifest_payload(manifest)))
    return manifest


def verify_evidence_manifest(manifest: EvidenceManifest, workspace: Path) -> EvidenceIntegrity:
    computed_manifest_hash = _sha256_bytes(_canonical_json(_manifest_payload(manifest)))
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


def create_evidence_bundle(
    manifest: EvidenceManifest,
    workspace: Path,
    bundle_root: Path,
) -> Path:
    """Crea una copia separata degli artefatti e la rende read-only per il checker."""
    expected_manifest = manifest.model_dump_json(indent=2) + "\n"
    manifest_path = bundle_root / "manifest.json"
    if bundle_root.exists():
        try:
            if manifest_path.read_text(encoding="utf-8") == expected_manifest:
                return bundle_root
        except OSError:
            pass
        raise ValueError(f"Bundle evidenze già presente ma non coerente per {manifest.run_id}.")

    parent = bundle_root.parent
    parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{manifest.run_id}-", dir=parent))
    workspace_root = workspace.resolve()
    artifacts_root = temporary / "artifacts"
    artifacts_root.mkdir()
    try:
        for artifact in manifest.artifacts:
            source = (workspace_root / artifact.path).resolve()
            if (
                not source.is_relative_to(workspace_root)
                or source == workspace_root
                or not source.is_file()
                or source.is_symlink()
            ):
                raise ValueError(f"Artefatto non valido nel bundle: {artifact.path}")
            destination = artifacts_root / artifact.path
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
            destination.chmod(0o444)
        manifest_path_tmp = temporary / "manifest.json"
        manifest_path_tmp.write_text(expected_manifest, encoding="utf-8")
        manifest_path_tmp.chmod(0o444)
        for directory in sorted(
            (path for path in temporary.rglob("*") if path.is_dir()),
            key=lambda path: len(path.parts),
            reverse=True,
        ):
            directory.chmod(0o555)
        temporary.chmod(0o555)
        os.replace(temporary, bundle_root)
    except Exception:
        for path in temporary.rglob("*"):
            if path.is_dir():
                path.chmod(0o755)
            else:
                path.chmod(0o644)
        temporary.chmod(0o755)
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return bundle_root


def run_independent_checker(bundle_root: Path) -> EvidenceCheckerResult:
    """Controlla il bundle senza ricevere accesso al workspace scrivibile del maker."""
    manifest_path = bundle_root / "manifest.json"
    manifest = EvidenceManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    integrity = verify_evidence_manifest(manifest, bundle_root / "artifacts")
    writable_mask = stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH
    paths = [bundle_root, manifest_path, *(bundle_root / "artifacts").rglob("*")]
    read_only = all(not (path.stat().st_mode & writable_mask) for path in paths)
    checks = [
        *integrity.checks,
        IntegrityCheck(
            id="contract",
            passed=manifest.contract.passed,
            detail=(
                "contratto delle evidenze soddisfatto"
                if manifest.contract.passed
                else "contratto delle evidenze non soddisfatto"
            ),
        ),
        IntegrityCheck(
            id="read_only_bundle",
            passed=read_only,
            detail="bundle read-only" if read_only else "bundle ancora scrivibile",
        ),
    ]
    return EvidenceCheckerResult(
        manifest_sha256=manifest.manifest_sha256,
        checked_at=_utc_now(),
        read_only=read_only,
        passed=all(check.passed for check in checks),
        checks=checks,
    )


def assess_delivery_readiness(
    manifest: EvidenceManifest,
    integrity: EvidenceIntegrity,
    checker: EvidenceCheckerResult | None,
    gate: dict[str, Any] | None,
) -> DeliveryReadiness:
    if not manifest.delivery.relevant:
        return DeliveryReadiness(relevant=False, ready=True, checks=[])
    provenance = manifest.provenance
    ci_passed = provenance.ci_status.casefold() in {"success", "passed", "succeeded"}
    approved = bool(
        gate
        and gate.get("decision") == "approved"
        and gate.get("manifest_sha256") == manifest.manifest_sha256
    )
    checks = [
        IntegrityCheck(
            id="integrity",
            passed=integrity.valid,
            detail="evidenze integre" if integrity.valid else "evidenze alterate o mancanti",
        ),
        IntegrityCheck(
            id="independent_checker",
            passed=bool(checker and checker.passed),
            detail=(
                "checker indipendente superato"
                if checker and checker.passed
                else "checker indipendente non superato"
            ),
        ),
        IntegrityCheck(
            id="isolated_branch",
            passed=bool(
                provenance.repository
                and provenance.branch
                and provenance.branch not in {"main", "master"}
            ),
            detail=provenance.branch or "branch Git non rilevato",
        ),
        IntegrityCheck(
            id="clean_worktree",
            passed=provenance.repository and not provenance.dirty,
            detail=(
                "worktree pulito"
                if provenance.repository and not provenance.dirty
                else "worktree con modifiche o non rilevato"
            ),
        ),
        IntegrityCheck(
            id="ci_green",
            passed=ci_passed,
            detail=f"{provenance.ci_provider}: {provenance.ci_status}",
        ),
        IntegrityCheck(
            id="preview_environment",
            passed=bool(provenance.preview_url),
            detail=provenance.preview_url or "preview non configurata",
        ),
        IntegrityCheck(
            id="rollback_plan",
            passed=bool(manifest.delivery.rollback_plan),
            detail=manifest.delivery.rollback_plan,
        ),
        IntegrityCheck(
            id="human_gate",
            passed=approved,
            detail=(
                "approvato da " + str(gate.get("decided_by", "utente"))
                if approved and gate
                else "approvazione umana mancante"
            ),
        ),
    ]
    return DeliveryReadiness(
        relevant=True,
        ready=all(check.passed for check in checks),
        checks=checks,
    )
