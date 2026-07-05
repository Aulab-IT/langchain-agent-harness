from pathlib import Path

import pytest

from agent_harness.evaluation import (
    ArmSummary,
    EvaluationArtifact,
    GateResult,
    save_proposal_evaluation,
)
from agent_harness.improve import (
    Proposal,
    load_overrides,
    overrides_fingerprint,
    select_runtime_overrides,
    write_proposal,
)
from agent_harness.promotion import (
    list_config_versions,
    promote_proposal,
    read_canary,
    restore_config_version,
)


def evaluated_proposal(tmp_path: Path, *, passed: bool = True) -> Path:
    path = write_proposal(
        Proposal(harness_max_tool_calls=20),
        "report",
        tmp_path / "improvements",
    )
    candidate = {"harness_max_tool_calls": 20}
    artifact = EvaluationArtifact(
        schema_version=2,
        evaluation_id="eval-1",
        proposal_name=path.name,
        created_at="2026-01-01T00:00:00+00:00",
        eval_set_hash="set",
        baseline_fingerprint=overrides_fingerprint({}),
        candidate_fingerprint=overrides_fingerprint(candidate),
        baseline=[],
        candidate=[],
        baseline_summary=ArmSummary(
            check_pass_rate=0.5,
            avg_check_score=0.5,
            completion_rate=0.5,
            total_tokens=100,
            elapsed_ms=100,
        ),
        candidate_summary=ArmSummary(
            check_pass_rate=1.0,
            avg_check_score=1.0,
            completion_rate=1.0,
            total_tokens=90,
            elapsed_ms=90,
        ),
        gate=GateResult(
            passed=passed,
            quality_delta=0.5,
            completion_delta=0.5,
            token_ratio=0.9,
            latency_ratio=0.9,
        ),
    )
    save_proposal_evaluation(path, artifact)
    return path


def test_promotion_requires_passed_evaluation(tmp_path: Path) -> None:
    proposal = evaluated_proposal(tmp_path, passed=False)

    with pytest.raises(ValueError, match="respinta"):
        promote_proposal(
            proposal,
            active_path=tmp_path / "active.toml",
            versions_dir=tmp_path / "versions",
            canary_path=tmp_path / "canary.json",
            mode="full",
        )


def test_canary_routes_stable_session_fraction(tmp_path: Path) -> None:
    proposal = evaluated_proposal(tmp_path)
    result = promote_proposal(
        proposal,
        active_path=tmp_path / "active.toml",
        versions_dir=tmp_path / "versions",
        canary_path=tmp_path / "canary.json",
        mode="canary",
        fraction=0.2,
    )

    assert result["mode"] == "canary"
    canary = read_canary(tmp_path / "canary.json")
    assert canary and canary["fraction"] == 0.2
    routed = [
        select_runtime_overrides({}, tmp_path / "canary.json", session_id=f"session-{index}")
        for index in range(100)
    ]
    selected = sum(bool(value) for value in routed)
    assert 10 <= selected <= 30


def test_full_promotion_versions_and_rolls_back(tmp_path: Path) -> None:
    proposal = evaluated_proposal(tmp_path)
    active = tmp_path / "active.toml"
    versions = tmp_path / "versions"
    canary = tmp_path / "canary.json"

    promoted = promote_proposal(
        proposal,
        active_path=active,
        versions_dir=versions,
        canary_path=canary,
        mode="full",
    )

    assert load_overrides(active) == {"harness_max_tool_calls": 20}
    assert promoted["version"]["source"] == proposal.name
    before = next(
        item
        for item in list_config_versions(versions)
        if item["source"].startswith("before:")
    )

    restored = restore_config_version(before["id"], versions, active, canary)

    assert restored == {}
    assert load_overrides(active) == {}
