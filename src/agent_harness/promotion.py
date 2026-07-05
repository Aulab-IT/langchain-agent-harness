from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from agent_harness.evaluation import EvaluationArtifact, load_proposal_evaluation
from agent_harness.improve import (
    load_overrides,
    overrides_fingerprint,
    replace_override_values,
    saved_overrides,
)

PromotionMode = Literal["canary", "full"]


def _version_id(values: dict[str, Any]) -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{stamp}-{overrides_fingerprint(values)[:8]}"


def record_config_version(
    values: dict[str, Any],
    versions_dir: Path,
    *,
    source: str,
) -> dict[str, Any]:
    versions_dir.mkdir(parents=True, exist_ok=True)
    version = {
        "id": _version_id(values),
        "created_at": datetime.now(UTC).isoformat(),
        "source": source[:240],
        "fingerprint": overrides_fingerprint(values),
        "overrides": values,
    }
    (versions_dir / f"{version['id']}.json").write_text(
        json.dumps(version, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return version


def list_config_versions(versions_dir: Path, *, limit: int = 100) -> list[dict[str, Any]]:
    if not versions_dir.is_dir():
        return []
    versions: list[dict[str, Any]] = []
    for path in sorted(versions_dir.glob("*.json"), reverse=True)[:limit]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(value, dict):
            versions.append(value)
    return versions


def restore_config_version(
    version_id: str,
    versions_dir: Path,
    active_path: Path,
    canary_path: Path,
) -> dict[str, Any]:
    if not version_id or Path(version_id).name != version_id:
        raise ValueError("Versione config non valida.")
    path = versions_dir / f"{version_id}.json"
    if not path.is_file():
        raise FileNotFoundError(version_id)
    version = json.loads(path.read_text(encoding="utf-8"))
    values = version.get("overrides", {})
    if not isinstance(values, dict):
        raise ValueError("Versione config corrotta.")
    current = load_overrides(active_path)
    record_config_version(current, versions_dir, source=f"before-rollback:{version_id}")
    restored = replace_override_values(values, active_path)
    canary_path.unlink(missing_ok=True)
    record_config_version(restored, versions_dir, source=f"rollback:{version_id}")
    return restored


def read_canary(canary_path: Path) -> dict[str, Any] | None:
    if not canary_path.is_file():
        return None
    try:
        value = json.loads(canary_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _validated_candidate(
    proposal_path: Path,
    active_path: Path,
) -> tuple[dict[str, Any], dict[str, Any], EvaluationArtifact]:
    proposal = saved_overrides(proposal_path)
    if not proposal:
        raise ValueError("Proposta senza override applicabili.")
    evaluation = load_proposal_evaluation(proposal_path)
    if evaluation is None:
        raise ValueError("Proposta non valutata.")
    if not evaluation.gate.passed:
        raise ValueError("Proposta respinta dal gate di regressione.")
    active = load_overrides(active_path)
    candidate = {**active, **proposal}
    if overrides_fingerprint(active) != evaluation.baseline_fingerprint:
        raise ValueError("Baseline cambiata dopo evaluation; rivalutare proposta.")
    if overrides_fingerprint(candidate) != evaluation.candidate_fingerprint:
        raise ValueError("Proposta cambiata dopo evaluation; rivalutare proposta.")
    return active, candidate, evaluation


def promote_proposal(
    proposal_path: Path,
    *,
    active_path: Path,
    versions_dir: Path,
    canary_path: Path,
    mode: PromotionMode = "canary",
    fraction: float = 0.2,
) -> dict[str, Any]:
    active, candidate, evaluation = _validated_candidate(proposal_path, active_path)
    if mode == "canary":
        if not 0.05 <= fraction <= 0.5:
            raise ValueError("Quota canary deve essere tra 0.05 e 0.5.")
        canary = {
            "source": proposal_path.name,
            "created_at": datetime.now(UTC).isoformat(),
            "fraction": fraction,
            "baseline_fingerprint": evaluation.baseline_fingerprint,
            "candidate_fingerprint": evaluation.candidate_fingerprint,
            "overrides": candidate,
        }
        canary_path.parent.mkdir(parents=True, exist_ok=True)
        canary_path.write_text(
            json.dumps(canary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return {"mode": mode, "active": active, "canary": canary, "version": None}

    record_config_version(active, versions_dir, source=f"before:{proposal_path.name}")
    applied = replace_override_values(candidate, active_path)
    canary_path.unlink(missing_ok=True)
    version = record_config_version(applied, versions_dir, source=proposal_path.name)
    return {"mode": mode, "active": applied, "canary": None, "version": version}
