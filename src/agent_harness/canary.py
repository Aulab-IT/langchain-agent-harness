from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field

CANARY_EVENT_TYPES = (
    "config.selected",
    "grader.completed",
    "run.completed",
)
MINIMUM_RUNS_PER_ARM = 5


class CanaryArmMetrics(BaseModel):
    total_runs: int = 0
    successful_runs: int = 0
    incomplete_runs: int = 0
    failed_runs: int = 0
    cancelled_runs: int = 0
    success_rate: float = 0.0
    failure_rate: float = 0.0
    graded_runs: int = 0
    grader_pass_rate: float = 0.0
    grader_avg_score: float = 0.0
    avg_tokens: int = 0
    avg_latency_ms: int = 0


class CanaryAnalysis(BaseModel):
    status: Literal["inactive", "collecting", "passed", "failed"]
    source: str = ""
    started_at: str = ""
    minimum_runs_per_arm: int = MINIMUM_RUNS_PER_ARM
    baseline: CanaryArmMetrics = Field(default_factory=CanaryArmMetrics)
    canary: CanaryArmMetrics = Field(default_factory=CanaryArmMetrics)
    success_delta: float = 0.0
    grader_delta: float = 0.0
    token_ratio: float = 0.0
    latency_ratio: float = 0.0
    reasons: list[str] = Field(default_factory=list)


@dataclass
class _Accumulator:
    total_runs: int = 0
    successful_runs: int = 0
    incomplete_runs: int = 0
    failed_runs: int = 0
    cancelled_runs: int = 0
    graded_runs: int = 0
    grader_passed: int = 0
    grader_score_sum: float = 0.0
    total_tokens: int = 0
    latency_sum_ms: int = 0
    latency_count: int = 0

    def metrics(self) -> CanaryArmMetrics:
        total = max(self.total_runs, 1)
        graded = max(self.graded_runs, 1)
        return CanaryArmMetrics(
            total_runs=self.total_runs,
            successful_runs=self.successful_runs,
            incomplete_runs=self.incomplete_runs,
            failed_runs=self.failed_runs,
            cancelled_runs=self.cancelled_runs,
            success_rate=round(self.successful_runs / total, 3),
            failure_rate=round(self.failed_runs / total, 3),
            graded_runs=self.graded_runs,
            grader_pass_rate=round(self.grader_passed / graded, 3),
            grader_avg_score=round(self.grader_score_sum / graded, 3),
            avg_tokens=round(self.total_tokens / total),
            avg_latency_ms=(
                round(self.latency_sum_ms / self.latency_count)
                if self.latency_count
                else 0
            ),
        )


def analyze_canary(
    runs: list[dict[str, Any]],
    events: list[dict[str, Any]],
    canary_config: dict[str, Any] | None,
) -> CanaryAnalysis:
    """Confronta solo run attribuiti alla canary attiva e ai suoi fingerprint."""
    if not canary_config:
        return CanaryAnalysis(status="inactive")
    source = str(canary_config.get("source", ""))
    started_at = str(canary_config.get("created_at", ""))
    baseline_fingerprint = str(canary_config.get("baseline_fingerprint", ""))
    candidate_fingerprint = str(canary_config.get("candidate_fingerprint", ""))
    selected: dict[str, str] = {}
    completed_payloads: dict[str, dict[str, Any]] = {}
    latest_grades: dict[str, dict[str, Any]] = {}
    latency: dict[str, int] = {}
    for event in events:
        run_id = str(event.get("run_id", ""))
        payload = event.get("payload", {}) or {}
        if event.get("type") == "config.selected":
            if started_at and str(event.get("created_at", "")) < started_at:
                continue
            arm = str(payload.get("arm", ""))
            fingerprint = str(payload.get("fingerprint", ""))
            event_source = str(payload.get("source", ""))
            if event_source != source:
                continue
            baseline_match = arm == "baseline" and fingerprint == baseline_fingerprint
            canary_match = arm == "canary" and fingerprint == candidate_fingerprint
            if baseline_match or canary_match:
                selected[run_id] = arm
        elif event.get("type") == "run.completed":
            completed_payloads[run_id] = payload
            latency[run_id] = int(payload.get("elapsed_ms", 0) or 0)
        elif event.get("type") == "grader.completed":
            latest_grades[run_id] = payload

    accumulators = {"baseline": _Accumulator(), "canary": _Accumulator()}
    for run in runs:
        run_id = str(run.get("id", ""))
        selected_arm = selected.get(run_id)
        if selected_arm is None:
            continue
        accumulator = accumulators[selected_arm]
        accumulator.total_runs += 1
        status = str(run.get("status", ""))
        if status == "completed":
            if completed_payloads.get(run_id, {}).get("completed") is False:
                accumulator.incomplete_runs += 1
            else:
                accumulator.successful_runs += 1
        elif status == "failed":
            accumulator.failed_runs += 1
        elif status == "cancelled":
            accumulator.cancelled_runs += 1
        usage = run.get("usage", {}) or {}
        accumulator.total_tokens += int(usage.get("total_tokens", 0) or 0)
        if latency.get(run_id):
            accumulator.latency_sum_ms += latency[run_id]
            accumulator.latency_count += 1
        grade = latest_grades.get(run_id)
        if grade:
            accumulator.graded_runs += 1
            if grade.get("passed"):
                accumulator.grader_passed += 1
            accumulator.grader_score_sum += float(grade.get("score", 0.0) or 0.0)

    baseline = accumulators["baseline"].metrics()
    canary = accumulators["canary"].metrics()
    success_delta = round(canary.success_rate - baseline.success_rate, 3)
    grader_delta = round(canary.grader_avg_score - baseline.grader_avg_score, 3)
    token_ratio = round(canary.avg_tokens / max(baseline.avg_tokens, 1), 3)
    latency_ratio = round(
        canary.avg_latency_ms / max(baseline.avg_latency_ms, 1),
        3,
    )
    collecting_reasons: list[str] = []
    if baseline.total_runs < MINIMUM_RUNS_PER_ARM:
        collecting_reasons.append(
            f"Servono {MINIMUM_RUNS_PER_ARM - baseline.total_runs} run baseline."
        )
    if canary.total_runs < MINIMUM_RUNS_PER_ARM:
        collecting_reasons.append(
            f"Servono {MINIMUM_RUNS_PER_ARM - canary.total_runs} run canary."
        )
    if collecting_reasons:
        return CanaryAnalysis(
            status="collecting",
            source=source,
            started_at=started_at,
            baseline=baseline,
            canary=canary,
            success_delta=success_delta,
            grader_delta=grader_delta,
            token_ratio=token_ratio,
            latency_ratio=latency_ratio,
            reasons=collecting_reasons,
        )

    reasons: list[str] = []
    if success_delta < -0.05:
        reasons.append("Success rate canary oltre 5 punti sotto baseline.")
    if canary.failure_rate > baseline.failure_rate + 0.05:
        reasons.append("Failure rate canary oltre 5 punti sopra baseline.")
    if baseline.graded_runs and canary.graded_runs and grader_delta < -0.03:
        reasons.append("Score grader canary oltre 0.03 sotto baseline.")
    if token_ratio > 1.2:
        reasons.append("Token medi canary oltre budget +20%.")
    if latency_ratio > 1.3:
        reasons.append("Latenza media canary oltre budget +30%.")
    return CanaryAnalysis(
        status="failed" if reasons else "passed",
        source=source,
        started_at=started_at,
        baseline=baseline,
        canary=canary,
        success_delta=success_delta,
        grader_delta=grader_delta,
        token_ratio=token_ratio,
        latency_ratio=latency_ratio,
        reasons=reasons,
    )
