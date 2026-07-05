import tomllib
from pathlib import Path

import pytest

from agent_harness.improve import (
    OVERRIDE_WHITELIST,
    Proposal,
    build_report,
    load_overrides,
    propose,
    replace_override_values,
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


def test_build_report_aggregates_correlated_run_events() -> None:
    runs = [
        {"id": "ok", "status": "completed", "usage": {"total_tokens": 100}},
        {"id": "failed", "status": "failed", "usage": {"total_tokens": 200}},
        {"id": "incomplete", "status": "completed", "usage": {"total_tokens": 50}},
        {"id": "cancelled", "status": "cancelled", "usage": {"total_tokens": 0}},
    ]
    events = [
        {"run_id": "ok", "type": "run.completed", "payload": {"completed": True}},
        {
            "run_id": "incomplete",
            "type": "run.completed",
            "payload": {"completed": False},
        },
        {
            "run_id": "ok",
            "type": "grader.completed",
            "payload": {
                "passed": True,
                "score": 0.9,
                "feedback": "Buono.",
                "criteria_scores": {"completezza": 1.0, "verifica": 0.8},
            },
        },
        {
            "run_id": "incomplete",
            "type": "grader.completed",
            "payload": {
                "passed": False,
                "score": 0.3,
                "feedback": "Manca verifica.",
                "criteria_scores": {"completezza": 0.4, "verifica": 0.2},
            },
        },
        {
            "run_id": "ok",
            "type": "tool.started",
            "payload": {"tool": "web_search", "args": '{"query":"x"}'},
        },
        {
            "run_id": "ok",
            "type": "tool.started",
            "payload": {"tool": "web_search", "args": '{"query":"x"}'},
        },
        {
            "run_id": "ok",
            "type": "tool.failed",
            "payload": {"tool": "web_search", "elapsed_ms": 15_000},
        },
    ]

    report = build_report(runs, events)

    assert report.total_runs == 4
    assert report.successful_runs == 1
    assert report.failed_runs == 1
    assert report.incomplete_runs == 1
    assert report.cancelled_runs == 1
    assert report.total_tokens == 350
    assert report.grader_graded == 2
    assert report.grader_pass_rate == 0.5
    assert report.grader_avg_score == 0.6
    assert report.criteria_avg_scores == {"completezza": 0.7, "verifica": 0.5}
    assert report.grader_feedback == ["Buono.", "Manca verifica."]
    assert report.tool_calls["web_search"] == 2
    assert report.tool_errors["web_search"] == 1
    assert report.tool_error_rates["web_search"] == 0.5
    assert report.slow_tools["web_search"] == 1
    assert report.repeated_tool_calls["web_search"] == 1


@pytest.mark.asyncio
async def test_propose_exposes_only_whitelisted_overrides() -> None:
    proposal = Proposal(
        summary="s",
        findings=["f"],
        harness_max_tool_calls=60,
    )
    judge = FakeJudge(proposal)

    result = await propose("REPORT", judge)

    assert set(result.overrides) <= OVERRIDE_WHITELIST
    assert result.overrides == {"harness_max_tool_calls": 60}
    assert "dato non attendibile" in str(judge.prompts[0])


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


def test_load_overrides_ignores_frozen_rubric_threshold(tmp_path: Path) -> None:
    overrides_path = tmp_path / "harness_overrides.toml"
    overrides_path.write_text(
        "harness_max_tool_calls = 44\nharness_rubric_threshold = 0.1\n",
        encoding="utf-8",
    )

    assert load_overrides(overrides_path) == {"harness_max_tool_calls": 44}


def test_replace_overrides_writes_readable_toml(tmp_path: Path) -> None:
    overrides_path = tmp_path / "harness_overrides.toml"

    replace_override_values(
        {
            "harness_max_tool_calls": 55,
            "system_prompt_addendum": 'Aggiungi "prove" concrete.',
            "harness_rubric_threshold": 0.1,
        },
        overrides_path,
    )

    parsed = tomllib.loads(overrides_path.read_text(encoding="utf-8"))
    assert parsed["harness_max_tool_calls"] == 55
    assert parsed["system_prompt_addendum"] == 'Aggiungi "prove" concrete.'
    assert load_overrides(overrides_path) == parsed
