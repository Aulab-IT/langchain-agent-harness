from __future__ import annotations

import json
import re
import shutil
import time
import uuid
from collections.abc import Awaitable, Callable
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from agent_harness.improve import overrides_fingerprint

EVALUATION_SCHEMA_VERSION: Literal[2] = 2


class EvalCheck(BaseModel):
    type: Literal["answer_contains", "answer_regex", "file_exists", "file_contains"]
    value: str = Field(default="", max_length=2_000)
    path: str = Field(default="", max_length=240)


class EvalCase(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    goal: str = Field(min_length=1, max_length=20_000)
    checks: list[EvalCheck] = Field(min_length=1, max_length=20)
    files: dict[str, str] = Field(default_factory=dict)


class CaseResult(BaseModel):
    case_id: str
    checks_passed: bool
    check_score: float = Field(ge=0, le=1)
    protocol_completed: bool
    iterations: int = Field(ge=0)
    tokens: int = Field(ge=0)
    elapsed_ms: int = Field(ge=0)
    check_failures: list[str] = Field(default_factory=list)
    protocol_failures: list[str] = Field(default_factory=list)
    grader_feedback: list[str] = Field(default_factory=list)
    grader_scores: list[float] = Field(default_factory=list)
    error: str = ""


class ArmSummary(BaseModel):
    check_pass_rate: float
    avg_check_score: float
    completion_rate: float
    total_tokens: int
    elapsed_ms: int


class GateResult(BaseModel):
    passed: bool
    quality_delta: float
    completion_delta: float
    token_ratio: float
    latency_ratio: float
    check_regressions: list[str] = Field(default_factory=list)
    completion_regressions: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


class EvaluationArtifact(BaseModel):
    schema_version: Literal[2]
    evaluation_id: str
    proposal_name: str
    created_at: str
    eval_set_hash: str
    baseline_fingerprint: str
    candidate_fingerprint: str
    baseline: list[CaseResult]
    candidate: list[CaseResult]
    baseline_summary: ArmSummary
    candidate_summary: ArmSummary
    gate: GateResult


EvalExecutor = Callable[
    [EvalCase, dict[str, Any], str, Path],
    Awaitable[CaseResult],
]


def _confined_path(root: Path, relative: str) -> Path:
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"Path eval fuori workspace: {relative}") from exc
    return candidate


def load_eval_cases(path: Path) -> list[EvalCase]:
    """Carica un eval set locale e valida schema, path e dimensione."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list) or not 1 <= len(raw) <= 20:
        raise ValueError("Eval set deve contenere da 1 a 20 casi.")
    cases = [EvalCase.model_validate(item) for item in raw]
    if len({case.id for case in cases}) != len(cases):
        raise ValueError("Gli id dei casi eval devono essere univoci.")
    for case in cases:
        for relative, content in case.files.items():
            if len(relative) > 240 or len(content) > 100_000:
                raise ValueError(f"Fixture eval non valida: {case.id}")
            _confined_path(Path("/tmp/eval-workspace"), relative)
        for check in case.checks:
            if check.type.startswith("file_"):
                if not check.path:
                    raise ValueError(f"Check file senza path: {case.id}")
                _confined_path(Path("/tmp/eval-workspace"), check.path)
            elif not check.value:
                raise ValueError(f"Check risposta senza value: {case.id}")
    return cases


def eval_set_hash(cases: list[EvalCase]) -> str:
    import hashlib

    payload = json.dumps(
        [case.model_dump(mode="json") for case in cases],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def evaluate_checks(case: EvalCase, answer: str, workspace: Path) -> tuple[float, list[str]]:
    failures: list[str] = []
    for check in case.checks:
        if check.type == "answer_contains":
            if check.value.casefold() not in answer.casefold():
                failures.append(f"Risposta non contiene: {check.value}")
        elif check.type == "answer_regex":
            if re.search(check.value, answer, flags=re.IGNORECASE | re.MULTILINE) is None:
                failures.append(f"Risposta non soddisfa regex: {check.value}")
        elif check.type == "file_exists":
            if not _confined_path(workspace, check.path).is_file():
                failures.append(f"File mancante: {check.path}")
        elif check.type == "file_contains":
            target = _confined_path(workspace, check.path)
            if not target.is_file():
                failures.append(f"File mancante: {check.path}")
            elif check.value.casefold() not in target.read_text(
                encoding="utf-8", errors="replace"
            ).casefold():
                failures.append(f"{check.path} non contiene: {check.value}")
    score = round((len(case.checks) - len(failures)) / len(case.checks), 3)
    return score, failures


def summarize(results: list[CaseResult]) -> ArmSummary:
    count = max(len(results), 1)
    return ArmSummary(
        check_pass_rate=round(sum(result.checks_passed for result in results) / count, 3),
        avg_check_score=round(sum(result.check_score for result in results) / count, 3),
        completion_rate=round(sum(result.protocol_completed for result in results) / count, 3),
        total_tokens=sum(result.tokens for result in results),
        elapsed_ms=sum(result.elapsed_ms for result in results),
    )


def evaluate_gate(
    baseline: list[CaseResult],
    candidate: list[CaseResult],
) -> tuple[ArmSummary, ArmSummary, GateResult]:
    """Separa qualità verificata e affidabilità del protocollo di completion."""
    baseline_summary = summarize(baseline)
    candidate_summary = summarize(candidate)
    candidate_by_id = {result.case_id: result for result in candidate}
    check_regressions = [
        result.case_id
        for result in baseline
        if result.checks_passed
        and (
            result.case_id not in candidate_by_id
            or not candidate_by_id[result.case_id].checks_passed
        )
    ]
    completion_regressions = [
        result.case_id
        for result in baseline
        if result.protocol_completed
        and (
            result.case_id not in candidate_by_id
            or not candidate_by_id[result.case_id].protocol_completed
        )
    ]
    quality_delta = round(
        candidate_summary.avg_check_score - baseline_summary.avg_check_score,
        3,
    )
    completion_delta = round(
        candidate_summary.completion_rate - baseline_summary.completion_rate,
        3,
    )
    token_ratio = round(
        candidate_summary.total_tokens / max(baseline_summary.total_tokens, 1),
        3,
    )
    latency_ratio = round(
        candidate_summary.elapsed_ms / max(baseline_summary.elapsed_ms, 1),
        3,
    )
    efficiency_improved = token_ratio <= 0.95 or latency_ratio <= 0.95
    quality_improved = quality_delta >= 0.01
    completion_improved = completion_delta >= 0.01
    reasons: list[str] = []
    if check_regressions:
        reasons.append(f"Regressioni check su: {', '.join(check_regressions)}")
    if completion_regressions:
        reasons.append(
            f"Regressioni completion su: {', '.join(completion_regressions)}"
        )
    if candidate_summary.check_pass_rate < 0.8:
        reasons.append("Check pass rate candidato sotto 0.8.")
    if candidate_summary.completion_rate < 0.8:
        reasons.append("Completion protocollo candidato sotto 0.8.")
    if token_ratio > 1.2:
        reasons.append("Token candidato oltre budget +20%.")
    if latency_ratio > 1.3:
        reasons.append("Latenza candidata oltre budget +30%.")
    if not quality_improved and not completion_improved and not efficiency_improved:
        reasons.append(
            "Nessun miglioramento misurabile di qualità, completion o efficienza."
        )
    passed = not reasons
    return (
        baseline_summary,
        candidate_summary,
        GateResult(
            passed=passed,
            quality_delta=quality_delta,
            completion_delta=completion_delta,
            token_ratio=token_ratio,
            latency_ratio=latency_ratio,
            check_regressions=check_regressions,
            completion_regressions=completion_regressions,
            reasons=reasons,
        ),
    )


async def evaluate_candidate(
    *,
    proposal_name: str,
    baseline_overrides: dict[str, Any],
    candidate_overrides: dict[str, Any],
    cases: list[EvalCase],
    evaluations_dir: Path,
    executor: EvalExecutor,
) -> EvaluationArtifact:
    """Esegue confronto paired alternando ordine baseline/candidato per ridurre order bias."""
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    evaluation_id = f"{stamp}-{overrides_fingerprint(candidate_overrides)[:8]}"
    root = evaluations_dir / evaluation_id
    baseline: list[CaseResult] = []
    candidate: list[CaseResult] = []
    for index, case in enumerate(cases):
        arms = (
            (("baseline", baseline_overrides), ("candidate", candidate_overrides))
            if index % 2 == 0
            else (("candidate", candidate_overrides), ("baseline", baseline_overrides))
        )
        results: dict[str, CaseResult] = {}
        for arm, overrides in arms:
            try:
                results[arm] = await executor(case, overrides, arm, root)
            except Exception as exc:
                results[arm] = CaseResult(
                    case_id=case.id,
                    checks_passed=False,
                    check_score=0.0,
                    protocol_completed=False,
                    iterations=0,
                    tokens=0,
                    elapsed_ms=0,
                    check_failures=["Esecuzione eval fallita."],
                    protocol_failures=["Protocollo non eseguito."],
                    error=type(exc).__name__,
                )
        baseline.append(results["baseline"])
        candidate.append(results["candidate"])

    baseline_summary, candidate_summary, gate = evaluate_gate(baseline, candidate)
    artifact = EvaluationArtifact(
        schema_version=EVALUATION_SCHEMA_VERSION,
        evaluation_id=evaluation_id,
        proposal_name=proposal_name,
        created_at=datetime.now(UTC).isoformat(),
        eval_set_hash=eval_set_hash(cases),
        baseline_fingerprint=overrides_fingerprint(baseline_overrides),
        candidate_fingerprint=overrides_fingerprint(candidate_overrides),
        baseline=baseline,
        candidate=candidate,
        baseline_summary=baseline_summary,
        candidate_summary=candidate_summary,
        gate=gate,
    )
    root.mkdir(parents=True, exist_ok=True)
    (root / "result.json").write_text(
        artifact.model_dump_json(indent=2),
        encoding="utf-8",
    )
    return artifact


async def execute_eval_case(
    settings: Any,
    case: EvalCase,
    overrides: dict[str, Any],
    arm: str,
    evaluation_root: Path,
) -> CaseResult:
    """Esegue un caso col vero harness in workspace isolato e applica check deterministici."""
    from agent_harness.factory import build_harness
    from agent_harness.runner import (
        GoalRunner,
        has_successful_verification,
        requires_environment_verification,
    )
    from agent_harness.sandbox import session_sandbox_manager

    case_root = evaluation_root / arm / case.id
    workspace = case_root / "workspace"
    shutil.rmtree(case_root, ignore_errors=True)
    workspace.mkdir(parents=True)
    (case_root / "memories").mkdir()
    (case_root / "skills").mkdir()
    memory = settings.project_root / "memories" / "AGENTS.md"
    if memory.is_file():
        shutil.copy2(memory, case_root / "memories" / "AGENTS.md")
    if settings.skills_dir.is_dir():
        shutil.copytree(settings.skills_dir, case_root / "skills", dirs_exist_ok=True)
    for relative, content in case.files.items():
        target = _confined_path(workspace, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    session_id = str(uuid.uuid4())
    started = time.monotonic()
    grader_events: list[dict[str, Any]] = []

    async def approve(_: dict[str, Any]) -> bool:
        return True

    def capture_event(event: dict[str, Any]) -> None:
        if event.get("type") == "grader.completed":
            grader_events.append(event)

    try:
        eval_settings = settings.model_copy(
            update={
                "harness_max_continuations": settings.harness_eval_max_continuations,
            }
        )
        async with build_harness(
            eval_settings,
            session_id=session_id,
            workspace_dir=workspace,
            backend_root=case_root,
            run_id=f"eval-{session_id}",
            harness_overrides=overrides,
            config_arm=f"evaluation-{arm}",
        ) as harness:
            result = await GoalRunner(
                harness,
                approval_callback=approve,
                event_callback=capture_event,
            ).run(
                case.goal,
                thread_id=session_id,
            )
        tokens = 0
        for message in result.messages:
            metadata = getattr(message, "usage_metadata", None)
            if metadata:
                tokens += int(metadata.get("input_tokens", 0))
                tokens += int(metadata.get("output_tokens", 0))
        score, check_failures = evaluate_checks(case, result.text, workspace)
        protocol_failures: list[str] = []
        if not result.completed:
            if (
                requires_environment_verification(case.goal)
                and not has_successful_verification(result.messages)
            ):
                protocol_failures.append(
                    "Manca verifica ambiente riuscita tramite docker_exec."
                )
            elif grader_events:
                protocol_failures.append("Grader non superato entro budget evaluation.")
            else:
                protocol_failures.append(
                    "Harness non ha completato obiettivo entro budget evaluation."
                )
        grader_feedback = [
            str(event.get("feedback", "")).strip()
            for event in grader_events
            if str(event.get("feedback", "")).strip()
        ]
        grader_scores = [
            float(event.get("score", 0.0) or 0.0)
            for event in grader_events
        ]
        return CaseResult(
            case_id=case.id,
            checks_passed=not check_failures,
            check_score=score,
            protocol_completed=result.completed,
            iterations=result.iterations,
            tokens=tokens,
            elapsed_ms=round((time.monotonic() - started) * 1_000),
            check_failures=check_failures,
            protocol_failures=protocol_failures,
            grader_feedback=grader_feedback,
            grader_scores=grader_scores,
        )
    finally:
        with suppress(Exception):
            session_sandbox_manager.stop(session_id)


def save_proposal_evaluation(proposal_path: Path, artifact: EvaluationArtifact) -> Path:
    path = proposal_path.with_suffix(".evaluation.json")
    path.write_text(artifact.model_dump_json(indent=2), encoding="utf-8")
    return path


def load_proposal_evaluation(proposal_path: Path) -> EvaluationArtifact | None:
    path = proposal_path.with_suffix(".evaluation.json")
    if not path.is_file():
        return None
    try:
        return EvaluationArtifact.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
