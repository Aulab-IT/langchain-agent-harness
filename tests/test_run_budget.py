from __future__ import annotations

from decimal import Decimal

import pytest
from langchain.agents.middleware import ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, HumanMessage

from agent_harness.run_budget import (
    BudgetExceededError,
    BudgetRate,
    RunBudgetLimits,
    RunBudgetTracker,
    SubagentProgressState,
    build_fixed_model_budget_middleware,
)


def _limits(**changes: object) -> RunBudgetLimits:
    values = {
        "max_tokens": 1_000,
        "max_cost_usd": Decimal("10"),
        "max_seconds": 600,
        "max_model_calls": 10,
        "max_subagent_calls": 3,
        "max_subagent_model_calls": 8,
        "max_subagent_tokens": 50_000,
        "reserved_output_tokens": 100,
        "warning_ratio": 0.7,
    }
    values.update(changes)
    return RunBudgetLimits(**values)  # type: ignore[arg-type]


def _rate(input_price: str = "1", output_price: str = "2") -> BudgetRate:
    return BudgetRate.from_values("test", "model", input_price, output_price)


def test_projected_tokens_stop_before_provider_call() -> None:
    tracker = RunBudgetTracker(_limits(max_tokens=1_000))
    with pytest.raises(BudgetExceededError, match="supererebbe") as caught:
        tracker.before_model_call(
            kind="root", rate=_rate(), estimated_input_tokens=901
        )
    assert caught.value.dimension == "tokens"
    assert tracker.snapshot().model_calls == 0


def test_parallel_reservations_share_the_same_remaining_budget() -> None:
    tracker = RunBudgetTracker(_limits(max_tokens=1_000))
    tracker.before_model_call(kind="subagent:a", rate=_rate(), estimated_input_tokens=400)
    with pytest.raises(BudgetExceededError):
        tracker.before_model_call(kind="subagent:b", rate=_rate(), estimated_input_tokens=401)


def test_actual_provider_usage_reconciles_reservation_and_cost() -> None:
    tracker = RunBudgetTracker(_limits())
    reservation = tracker.before_model_call(
        kind="root", rate=_rate("10", "20"), estimated_input_tokens=200
    )
    response = AIMessage(
        content="ok",
        usage_metadata={"input_tokens": 250, "output_tokens": 50, "total_tokens": 300},
    )
    snapshot = tracker.complete_model_call(reservation, [response])
    assert snapshot.cumulative_input_tokens == 250
    assert snapshot.cumulative_output_tokens == 50
    assert snapshot.cost_usd == "0.0035"


def test_model_and_subagent_call_limits_are_hard() -> None:
    tracker = RunBudgetTracker(_limits(max_model_calls=1, max_subagent_calls=1))
    reservation = tracker.before_model_call(
        kind="root", rate=_rate(), estimated_input_tokens=10
    )
    tracker.record_estimated_call(reservation, "ok")
    with pytest.raises(BudgetExceededError) as model_error:
        tracker.before_model_call(kind="root", rate=_rate(), estimated_input_tokens=10)
    assert model_error.value.dimension == "model_calls"

    subagent_tracker = RunBudgetTracker(_limits(max_subagent_calls=1))
    subagent_tracker.start_subagent_call("a")
    with pytest.raises(BudgetExceededError) as subagent_error:
        subagent_tracker.start_subagent_call("b")
    assert subagent_error.value.dimension == "subagent_calls"


def test_warning_is_emitted_at_progressive_thresholds() -> None:
    events: list[dict[str, object]] = []
    tracker = RunBudgetTracker(_limits(warning_ratio=0.7), events.append)
    first = tracker.before_model_call(kind="root", rate=_rate(), estimated_input_tokens=600)
    tracker.record_estimated_call(first, "ok")
    second = tracker.before_model_call(kind="root", rate=_rate(), estimated_input_tokens=150)
    tracker.record_estimated_call(second, "ok")
    third = tracker.before_model_call(kind="root", rate=_rate(), estimated_input_tokens=100)
    tracker.record_estimated_call(third, "ok")
    warnings = [event for event in events if event["type"] == "budget.warning"]
    assert [event["level_percent"] for event in warnings] == [70, 85, 95]


def test_subagent_resume_does_not_consume_another_delegation() -> None:
    tracker = RunBudgetTracker(_limits(max_subagent_calls=1))
    assert tracker.start_subagent_call("researcher", "invocation-1") is True
    assert tracker.start_subagent_call("researcher", "invocation-1") is False
    assert tracker.snapshot().subagent_calls == 1


def test_single_subagent_has_local_model_call_limit() -> None:
    tracker = RunBudgetTracker(_limits(max_subagent_model_calls=1))
    reservation = tracker.before_model_call(
        kind="subagent:builder", rate=_rate(), estimated_input_tokens=10
    )
    tracker.record_estimated_call(reservation, "ok")
    with pytest.raises(BudgetExceededError) as caught:
        tracker.before_model_call(
            kind="subagent:builder", rate=_rate(), estimated_input_tokens=10
        )
    assert caught.value.dimension == "subagent_model_calls"


@pytest.mark.asyncio
async def test_subagent_last_model_call_is_reserved_for_final_response() -> None:
    events: list[dict[str, object]] = []
    tracker = RunBudgetTracker(_limits(max_subagent_model_calls=3), events.append)
    for _ in range(2):
        reservation = tracker.before_model_call(
            kind="subagent:builder", rate=_rate(), estimated_input_tokens=10
        )
        tracker.record_estimated_call(reservation, "working")
    progress = SubagentProgressState()
    progress.record(["validation_passed_with_warnings", "dependency_missing"])
    middleware = build_fixed_model_budget_middleware(
        tracker,
        _rate(),
        kind="subagent:builder",
        progress=progress,
        event_callback=events.append,
    )
    request = ModelRequest(  # type: ignore[arg-type]
        model=object(),
        messages=[HumanMessage(content="finish")],
        tools=[{"type": "function", "function": {"name": "execute"}}],
    )
    captured: ModelRequest | None = None

    attempts = 0

    async def handler(next_request: ModelRequest) -> ModelResponse:
        nonlocal attempts
        nonlocal captured
        attempts += 1
        captured = next_request
        if attempts == 1:
            transient = type("APIError", (Exception,), {})
            raise transient("You can retry your request")
        return ModelResponse(
            result=[
                AIMessage(
                    content="TASK_STATUS: COMPLETE\nEVIDENCE:\n- artifact validated",
                    usage_metadata={
                        "input_tokens": 10,
                        "output_tokens": 10,
                        "total_tokens": 20,
                    },
                )
            ]
        )

    await middleware.awrap_model_call(request, handler)

    assert captured is not None
    assert captured.tools == []
    assert "reserved final response call" in captured.system_message.text
    assert attempts == 2
    assert tracker.snapshot().by_call_kind["subagent:builder"]["model_calls"] == 3
    assert any(event["type"] == "subagent.finalization.forced" for event in events)
    assert any(event["type"] == "model.retrying" for event in events)
    assert any(event["type"] == "budget.retry_estimated" for event in events)
