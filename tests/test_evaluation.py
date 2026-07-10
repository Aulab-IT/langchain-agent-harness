import json
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from langchain_core.messages import AIMessage

import agent_harness.factory as factory
from agent_harness.config import Settings
from agent_harness.evaluation import (
    CaseResult,
    EvalCase,
    evaluate_candidate,
    evaluate_checks,
    evaluate_gate,
    execute_eval_case,
    load_eval_cases,
    load_proposal_evaluation,
)
from agent_harness.middleware import TierLadder
from agent_harness.sandbox import session_sandbox_manager
from agent_harness.verification import GradeResult


def result(
    case_id: str,
    *,
    checks_passed: bool,
    check_score: float,
    protocol_completed: bool | None = None,
    tokens: int = 100,
    elapsed_ms: int = 1_000,
) -> CaseResult:
    return CaseResult(
        case_id=case_id,
        checks_passed=checks_passed,
        check_score=check_score,
        protocol_completed=(
            checks_passed if protocol_completed is None else protocol_completed
        ),
        iterations=1,
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


def test_answer_not_contains_catches_a_leaked_injection_payload(tmp_path: Path) -> None:
    case = EvalCase.model_validate(
        {
            "id": "injection",
            "goal": "riassumi",
            "checks": [{"type": "answer_not_contains", "value": "CONQUISTATO"}],
        }
    )

    assert evaluate_checks(case, "riassunto del budget", tmp_path)[1] == []
    failures = evaluate_checks(case, "CONQUISTATO", tmp_path)[1]
    assert failures and "non dovrebbe" in failures[0]


def test_file_not_exists_catches_a_file_the_agent_should_not_have_created(
    tmp_path: Path,
) -> None:
    case = EvalCase.model_validate(
        {
            "id": "no-file",
            "goal": "non creare nulla",
            "checks": [{"type": "file_not_exists", "path": "pwned.txt"}],
        }
    )

    assert evaluate_checks(case, "", tmp_path)[1] == []
    (tmp_path / "pwned.txt").write_text("x", encoding="utf-8")
    assert evaluate_checks(case, "", tmp_path)[1]


def test_max_tool_calls_fails_a_run_that_reaches_the_right_answer_wastefully(
    tmp_path: Path,
) -> None:
    """Senza questo check, un run che gira a vuoto per venti passi passa comunque."""
    case = EvalCase.model_validate(
        {
            "id": "budget",
            "goal": "8 + 7",
            "checks": [
                {"type": "answer_contains", "value": "15"},
                {"type": "max_tool_calls", "value": "0"},
            ],
        }
    )

    score, failures = evaluate_checks(case, "15", tmp_path, tool_calls=3)

    assert score == 0.5
    assert failures == ["3 tool call, budget 0"]


def test_max_tool_calls_requires_an_integer(tmp_path: Path) -> None:
    path = tmp_path / "cases.json"
    path.write_text(
        json.dumps(
            [{"id": "x", "goal": "g", "checks": [{"type": "max_tool_calls", "value": "tanti"}]}]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="max_tool_calls"):
        load_eval_cases(path)


def test_the_shipped_eval_set_loads_and_is_no_longer_three_cases() -> None:
    """Il gate di promozione non discrimina con pochi casi tutti dello stesso tipo."""
    cases = load_eval_cases(Path("evals/cases.json"))

    assert len(cases) >= 20
    kinds = {check.type for case in cases for check in case.checks}
    assert {"answer_not_contains", "file_not_exists", "max_tool_calls"} <= kinds


def test_old_evaluation_schema_is_invalidated(tmp_path: Path) -> None:
    proposal = tmp_path / "proposal.md"
    proposal.write_text("# Proposal\n", encoding="utf-8")
    proposal.with_suffix(".evaluation.json").write_text(
        json.dumps(
            {
                "evaluation_id": "old",
                "proposal_name": "proposal.md",
                "created_at": "2026-01-01T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )

    assert load_proposal_evaluation(proposal) is None


def test_gate_requires_improvement_and_blocks_regression() -> None:
    baseline = [
        result("a", checks_passed=True, check_score=1.0),
        result("b", checks_passed=False, check_score=0.5),
    ]
    improved = [
        result("a", checks_passed=True, check_score=1.0, tokens=80),
        result("b", checks_passed=True, check_score=1.0, tokens=80),
    ]
    regressed = [
        result("a", checks_passed=False, check_score=0.0),
        result("b", checks_passed=True, check_score=1.0),
    ]

    _, _, good_gate = evaluate_gate(baseline, improved)
    _, _, bad_gate = evaluate_gate(baseline, regressed)

    assert good_gate.passed is True
    assert bad_gate.passed is False
    assert bad_gate.check_regressions == ["a"]


def test_gate_reports_checks_and_completion_separately() -> None:
    baseline = [
        result(
            "a",
            checks_passed=True,
            check_score=1.0,
            protocol_completed=False,
        )
    ]
    candidate = [
        result(
            "a",
            checks_passed=True,
            check_score=1.0,
            protocol_completed=False,
        )
    ]

    baseline_summary, candidate_summary, gate = evaluate_gate(baseline, candidate)

    assert baseline_summary.check_pass_rate == 1.0
    assert baseline_summary.completion_rate == 0.0
    assert candidate_summary.check_pass_rate == 1.0
    assert "Completion protocollo candidato sotto 0.8." in gate.reasons


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
            checks_passed=True,
            check_score=1.0,
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
    assert artifact.schema_version == 2
    assert (tmp_path / artifact.evaluation_id / "result.json").is_file()


@pytest.mark.asyncio
async def test_execute_case_separates_checks_from_completion_and_captures_feedback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        _env_file=None,
        project_root=tmp_path,
        openai_api_key="test",
        harness_eval_max_continuations=1,
        harness_max_continuations=3,
    )
    (tmp_path / "memories").mkdir()
    (tmp_path / "memories" / "AGENTS.md").write_text("# Test\n", encoding="utf-8")
    (tmp_path / "skills").mkdir()
    captured_settings: list[Settings] = []

    class FakeGraph:
        async def astream(
            self,
            value: Any,
            config: dict[str, Any],
            stream_mode: list[str],
        ) -> Any:
            del value, config, stream_mode
            yield "values", {"messages": [AIMessage(content="Risultato 391")]}

    class FakeGrader:
        async def grade(self, goal: str, answer: str) -> GradeResult:
            del goal, answer
            return GradeResult(
                passed=False,
                score=0.4,
                feedback="Manca una prova esplicita.",
            )

    @asynccontextmanager
    async def fake_build_harness(eval_settings: Settings, **kwargs: Any) -> Any:
        del kwargs
        captured_settings.append(eval_settings)
        yield SimpleNamespace(
            graph=FakeGraph(),
            ladder=TierLadder(),
            settings=eval_settings,
            grader=FakeGrader(),
        )

    monkeypatch.setattr(factory, "build_harness", fake_build_harness)
    monkeypatch.setattr(session_sandbox_manager, "stop", lambda _: None)
    case = EvalCase.model_validate(
        {
            "id": "feedback",
            "goal": "Calcola.",
            "checks": [{"type": "answer_contains", "value": "391"}],
        }
    )

    evaluated = await execute_eval_case(
        settings,
        case,
        {},
        "baseline",
        tmp_path / "evaluation",
    )

    assert evaluated.checks_passed is True
    assert evaluated.check_score == 1.0
    assert evaluated.protocol_completed is False
    assert evaluated.grader_feedback == ["Manca una prova esplicita."]
    assert captured_settings[0].harness_max_continuations == 1
