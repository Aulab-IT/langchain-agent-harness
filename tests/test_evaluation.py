import json
from pathlib import Path
from typing import Any

import pytest

from agent_harness.evaluation import (
    CaseResult,
    EvalCase,
    evaluate_candidate,
    evaluate_checks,
    evaluate_gate,
    load_eval_cases,
)


def result(
    case_id: str,
    *,
    passed: bool,
    score: float,
    tokens: int = 100,
    elapsed_ms: int = 1_000,
) -> CaseResult:
    return CaseResult(
        case_id=case_id,
        passed=passed,
        score=score,
        completed=passed,
        tokens=tokens,
        elapsed_ms=elapsed_ms,
    )


def test_load_eval_cases_rejects_traversal(tmp_path: Path) -> None:
    path = tmp_path / "cases.json"
    path.write_text(
        json.dumps(
            [
                {
                    "id": "bad",
                    "goal": "test",
                    "checks": [{"type": "file_exists", "path": "../secret"}],
                }
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="fuori workspace"):
        load_eval_cases(path)


def test_deterministic_checks_cover_answer_and_files(tmp_path: Path) -> None:
    (tmp_path / "result.txt").write_text("HARNESS_OK=42", encoding="utf-8")
    case = EvalCase.model_validate(
        {
            "id": "checks",
            "goal": "test",
            "checks": [
                {"type": "answer_contains", "value": "391"},
                {"type": "answer_regex", "value": r"verificat[oa]"},
                {"type": "file_exists", "path": "result.txt"},
                {"type": "file_contains", "path": "result.txt", "value": "ok=42"},
            ],
        }
    )

    score, failures = evaluate_checks(case, "391 verificato", tmp_path)

    assert score == 1.0
    assert failures == []


def test_gate_requires_improvement_and_blocks_regression() -> None:
    baseline = [result("a", passed=True, score=1.0), result("b", passed=False, score=0.5)]
    improved = [
        result("a", passed=True, score=1.0, tokens=80),
        result("b", passed=True, score=1.0, tokens=80),
    ]
    regressed = [
        result("a", passed=False, score=0.0),
        result("b", passed=True, score=1.0),
    ]

    _, _, good_gate = evaluate_gate(baseline, improved)
    _, _, bad_gate = evaluate_gate(baseline, regressed)

    assert good_gate.passed is True
    assert bad_gate.passed is False
    assert bad_gate.regressions == ["a"]


@pytest.mark.asyncio
async def test_evaluate_candidate_alternates_arms_and_writes_artifact(tmp_path: Path) -> None:
    cases = [
        EvalCase.model_validate(
            {
                "id": case_id,
                "goal": "test",
                "checks": [{"type": "answer_contains", "value": "ok"}],
            }
        )
        for case_id in ("a", "b")
    ]
    order: list[tuple[str, str]] = []

    async def executor(
        case: EvalCase,
        overrides: dict[str, Any],
        arm: str,
        root: Path,
    ) -> CaseResult:
        del overrides, root
        order.append((case.id, arm))
        return result(
            case.id,
            passed=True,
            score=1.0,
            tokens=80 if arm == "candidate" else 100,
        )

    artifact = await evaluate_candidate(
        proposal_name="proposal.md",
        baseline_overrides={},
        candidate_overrides={"harness_max_tool_calls": 30},
        cases=cases,
        evaluations_dir=tmp_path,
        executor=executor,
    )

    assert order == [
        ("a", "baseline"),
        ("a", "candidate"),
        ("b", "candidate"),
        ("b", "baseline"),
    ]
    assert artifact.gate.passed is True
    assert (tmp_path / artifact.evaluation_id / "result.json").is_file()
