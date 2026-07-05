from typing import Any

from agent_harness.canary import analyze_canary


def canary_config() -> dict[str, Any]:
    return {
        "source": "proposal.md",
        "created_at": "2026-01-01T00:00:00+00:00",
        "baseline_fingerprint": "base",
        "candidate_fingerprint": "candidate",
    }


def arm_data(
    arm: str,
    *,
    count: int,
    successful: int,
    tokens: int,
    score: float = 0.8,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    runs: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    fingerprint = "base" if arm == "baseline" else "candidate"
    for index in range(count):
        run_id = f"{arm}-{index}"
        completed = index < successful
        runs.append(
            {
                "id": run_id,
                "status": "completed",
                "usage": {"total_tokens": tokens},
            }
        )
        events.extend(
            [
                {
                    "run_id": run_id,
                    "type": "config.selected",
                    "created_at": "2026-01-02T00:00:00+00:00",
                    "payload": {
                        "arm": arm,
                        "fingerprint": fingerprint,
                        "source": "proposal.md",
                    },
                },
                {
                    "run_id": run_id,
                    "type": "grader.completed",
                    "payload": {"passed": score >= 0.7, "score": score},
                },
                {
                    "run_id": run_id,
                    "type": "run.completed",
                    "payload": {
                        "completed": completed,
                        "elapsed_ms": 1_000,
                    },
                },
            ]
        )
    return runs, events


def combined(
    baseline: tuple[list[dict[str, Any]], list[dict[str, Any]]],
    canary: tuple[list[dict[str, Any]], list[dict[str, Any]]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    return baseline[0] + canary[0], baseline[1] + canary[1]


def test_canary_analysis_collects_minimum_sample() -> None:
    runs, events = combined(
        arm_data("baseline", count=4, successful=4, tokens=100),
        arm_data("canary", count=2, successful=2, tokens=90),
    )

    analysis = analyze_canary(runs, events, canary_config())

    assert analysis.status == "collecting"
    assert analysis.baseline.total_runs == 4
    assert analysis.canary.total_runs == 2
    assert "Servono 3 run canary." in analysis.reasons


def test_canary_analysis_passes_non_inferior_candidate() -> None:
    runs, events = combined(
        arm_data("baseline", count=5, successful=5, tokens=100),
        arm_data("canary", count=5, successful=5, tokens=90),
    )

    analysis = analyze_canary(runs, events, canary_config())

    assert analysis.status == "passed"
    assert analysis.success_delta == 0.0
    assert analysis.token_ratio == 0.9
    assert analysis.reasons == []


def test_canary_analysis_rejects_quality_and_cost_regression() -> None:
    runs, events = combined(
        arm_data("baseline", count=5, successful=5, tokens=100, score=0.9),
        arm_data("canary", count=5, successful=3, tokens=140, score=0.7),
    )

    analysis = analyze_canary(runs, events, canary_config())

    assert analysis.status == "failed"
    assert analysis.success_delta == -0.4
    assert analysis.token_ratio == 1.4
    assert any("Success rate" in reason for reason in analysis.reasons)
    assert any("Token medi" in reason for reason in analysis.reasons)


def test_canary_analysis_ignores_old_or_mismatched_attribution() -> None:
    runs, events = arm_data("canary", count=1, successful=1, tokens=10)
    events[0]["created_at"] = "2025-12-31T23:00:00+00:00"
    events.append(
        {
            "run_id": runs[0]["id"],
            "type": "config.selected",
            "created_at": "2026-01-02T00:00:00+00:00",
            "payload": {
                "arm": "canary",
                "fingerprint": "wrong",
                "source": "proposal.md",
            },
        }
    )

    analysis = analyze_canary(runs, events, canary_config())

    assert analysis.canary.total_runs == 0
