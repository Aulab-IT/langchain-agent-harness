from types import SimpleNamespace
from typing import Any

import pytest

from agent_harness.verification import RubricGrader


class FakeJudge:
    def __init__(
        self,
        completezza: float,
        verifica: float,
        aderenza: float,
        sicurezza: float,
        feedback: str = "",
    ) -> None:
        self._result = SimpleNamespace(
            completezza=completezza,
            verifica=verifica,
            aderenza=aderenza,
            sicurezza=sicurezza,
            feedback=feedback,
        )
        self.prompts: list[Any] = []

    async def ainvoke(self, prompt: Any) -> Any:
        self.prompts.append(prompt)
        return self._result


@pytest.mark.asyncio
async def test_grader_averages_scores_and_applies_threshold() -> None:
    grader = RubricGrader(FakeJudge(1.0, 1.0, 0.0, 0.0, "feedback"), threshold=0.7)

    result = await grader.grade("obiettivo", "risposta")

    assert result.score == 0.5
    assert result.passed is False
    assert result.feedback == "feedback"
    assert result.criteria_scores == {
        "completezza": 1.0,
        "verifica": 1.0,
        "aderenza": 0.0,
        "sicurezza": 0.0,
    }


@pytest.mark.asyncio
async def test_grader_passes_when_above_threshold() -> None:
    grader = RubricGrader(FakeJudge(0.9, 0.8, 0.9, 0.8), threshold=0.7)

    result = await grader.grade("obiettivo", "risposta")

    assert result.passed is True
    assert result.score == pytest.approx(0.85)


@pytest.mark.asyncio
async def test_grader_clamps_out_of_range_scores() -> None:
    grader = RubricGrader(FakeJudge(2.0, -1.0, 1.0, 0.0), threshold=0.4)

    result = await grader.grade("obiettivo", "risposta")

    assert result.criteria_scores == {
        "completezza": 1.0,
        "verifica": 0.0,
        "aderenza": 1.0,
        "sicurezza": 0.0,
    }
    assert result.score == 0.5


@pytest.mark.asyncio
async def test_grader_prompt_contains_goal_and_answer() -> None:
    judge = FakeJudge(1.0, 1.0, 1.0, 1.0)
    grader = RubricGrader(judge)

    await grader.grade("OBIETTIVO-X", "RISPOSTA-Y")

    rendered = str(judge.prompts[0])
    assert "OBIETTIVO-X" in rendered
    assert "RISPOSTA-Y" in rendered
