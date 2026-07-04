import tomllib
from pathlib import Path

import pytest

from agent_harness.improve import (
    OVERRIDE_WHITELIST,
    Proposal,
    apply_override_values,
    apply_overrides,
    build_report,
    load_overrides,
    propose,
    saved_overrides,
    write_proposal,
)


class FakeJudge:
    def __init__(self, proposal: Proposal) -> None:
        self.proposal = proposal
        self.prompts: list[object] = []

    async def ainvoke(self, prompt: object) -> Proposal:
        self.prompts.append(prompt)
        return self.proposal


def test_build_report_aggregates_events_and_audit() -> None:
    events = [
        {"type": "run.completed", "payload": {}},
        {"type": "run.failed", "payload": {}},
        {"type": "grader.completed", "payload": {"passed": True, "score": 0.9}},
        {"type": "grader.completed", "payload": {"passed": False, "score": 0.3}},
    ]
    audit = [
        '{"tool": "docker_exec", "status": "error", "elapsed_ms": 100}',
        '{"tool": "web_search", "status": "ok", "elapsed_ms": 15000}',
        "not-json",
    ]

    report = build_report(events, audit)

    assert report.total_runs == 2
    assert report.failed_runs == 1
    assert report.grader_graded == 2
    assert report.grader_pass_rate == 0.5
    assert report.grader_avg_score == 0.6
    assert report.tool_errors["docker_exec"] == 1
    assert report.slow_tools["web_search"] == 1


@pytest.mark.asyncio
async def test_propose_exposes_only_whitelisted_overrides() -> None:
    proposal = Proposal(
        summary="s",
        findings=["f"],
        harness_max_tool_calls=60,
        harness_rubric_threshold=None,
    )

    result = await propose("REPORT", FakeJudge(proposal))

    assert set(result.overrides) <= OVERRIDE_WHITELIST
    assert result.overrides == {"harness_max_tool_calls": 60}


def test_write_proposal_does_not_touch_sources(tmp_path: Path) -> None:
    proposal = Proposal(summary="s", findings=["a"], harness_max_tool_calls=50)
    improvements = tmp_path / "improvements"

    path = write_proposal(proposal, "REPORT", improvements)

    assert path.exists()
    assert path.parent == improvements
    # Nessun file di override creato senza apply.
    assert not (tmp_path / "harness_overrides.toml").exists()


def test_write_proposal_saves_applicable_sidecar(tmp_path: Path) -> None:
    proposal = Proposal(summary="s", harness_max_tool_calls=44)
    improvements = tmp_path / "improvements"

    path = write_proposal(proposal, "REPORT", improvements)

    assert path.with_suffix(".overrides.json").is_file()
    assert saved_overrides(path) == {"harness_max_tool_calls": 44}


def test_saved_overrides_applies_to_toml(tmp_path: Path) -> None:
    path = write_proposal(Proposal(harness_rubric_threshold=0.9), "R", tmp_path / "improvements")
    overrides_path = tmp_path / "harness_overrides.toml"

    applied = apply_override_values(saved_overrides(path), overrides_path)

    assert applied == {"harness_rubric_threshold": 0.9}
    assert load_overrides(overrides_path) == {"harness_rubric_threshold": 0.9}


def test_apply_overrides_writes_readable_toml(tmp_path: Path) -> None:
    proposal = Proposal(
        harness_max_tool_calls=55,
        harness_rubric_threshold=0.8,
        system_prompt_addendum='Aggiungi "prove" concrete.',
    )
    overrides_path = tmp_path / "harness_overrides.toml"

    apply_overrides(proposal, overrides_path)

    parsed = tomllib.loads(overrides_path.read_text(encoding="utf-8"))
    assert parsed["harness_max_tool_calls"] == 55
    assert parsed["harness_rubric_threshold"] == 0.8
    assert parsed["system_prompt_addendum"] == 'Aggiungi "prove" concrete.'
    assert load_overrides(overrides_path) == parsed
