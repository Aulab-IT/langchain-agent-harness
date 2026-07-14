from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from langchain_core.messages import AIMessage

import agent_harness.model_preflight as preflight
from agent_harness.config import Settings
from agent_harness.model_preflight import ModelPreflightError
from agent_harness.run_budget import (
    BudgetExceededError,
    RunBudgetLimits,
    RunBudgetTracker,
)


class FakeModel:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls = 0

    async def ainvoke(self, messages: list[Any]) -> AIMessage:
        assert messages
        self.calls += 1
        if self.error:
            raise self.error
        return AIMessage(content="OK")


def _budget(*, max_cost_usd: str = "10") -> RunBudgetTracker:
    return RunBudgetTracker(
        RunBudgetLimits(
            max_tokens=100_000,
            max_cost_usd=Decimal(max_cost_usd),
            max_seconds=60,
            max_model_calls=10,
            max_subagent_calls=2,
            max_subagent_model_calls=2,
            max_subagent_tokens=50_000,
            reserved_output_tokens=100,
        )
    )


@pytest.mark.asyncio
async def test_preflight_deduplicates_same_provider_model_and_caches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = FakeModel()
    settings = Settings(
        _env_file=None,
        openai_api_key="test",
        harness_model_preflight_ttl_seconds=300,
    )
    preflight.clear_preflight_cache()
    monkeypatch.setattr(
        preflight,
        "build_tier_models",
        lambda _: {
            "low": SimpleNamespace(model=model),
            "mid": SimpleNamespace(model=model),
            "high": SimpleNamespace(model=model),
        },
    )
    monkeypatch.setattr(
        preflight,
        "tier_spec",
        lambda _settings, tier: SimpleNamespace(provider="openai", name="same-model"),
    )

    events: list[dict[str, Any]] = []
    await preflight.preflight_tier_models(
        settings, ("low", "mid"), event_callback=events.append
    )
    await preflight.preflight_tier_models(
        settings, ("low", "mid"), event_callback=events.append
    )

    assert model.calls == 1
    assert events[-1]["cached"] is True


@pytest.mark.asyncio
async def test_preflight_failure_names_provider_model_and_emits_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = FakeModel(RuntimeError("model_not_found"))
    settings = Settings(_env_file=None, openai_api_key="test")
    preflight.clear_preflight_cache()
    monkeypatch.setattr(
        preflight,
        "build_tier_models",
        lambda _: {tier: SimpleNamespace(model=model) for tier in ("low", "mid", "high")},
    )
    monkeypatch.setattr(
        preflight,
        "tier_spec",
        lambda _settings, tier: SimpleNamespace(provider="openai", name="missing-model"),
    )
    events: list[dict[str, Any]] = []

    with pytest.raises(ModelPreflightError, match="openai/missing-model"):
        await preflight.preflight_tier_models(
            settings, ("low",), event_callback=events.append
        )

    assert events[-1]["type"] == "model.preflight.failed"


@pytest.mark.asyncio
async def test_preflight_stops_before_provider_when_cost_budget_is_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = FakeModel()
    settings = Settings(_env_file=None, openai_api_key="test")
    preflight.clear_preflight_cache()
    monkeypatch.setattr(
        preflight,
        "build_tier_models",
        lambda _: {tier: SimpleNamespace(model=model) for tier in ("low", "mid", "high")},
    )
    monkeypatch.setattr(
        preflight,
        "tier_spec",
        lambda _settings, tier: SimpleNamespace(
            provider="openai",
            name=f"model-{tier}",
            price_in=1.0,
            price_out=6.0,
        ),
    )
    tracker = _budget(max_cost_usd="0")
    events: list[dict[str, Any]] = []

    with pytest.raises(BudgetExceededError) as caught:
        await preflight.preflight_tier_models(
            settings,
            ("low",),
            event_callback=events.append,
            budget_tracker=tracker,
        )

    assert caught.value.dimension == "cost"
    assert model.calls == 0
    assert tracker.snapshot().model_calls == 0
    assert "model.preflight.started" not in {event["type"] for event in events}


@pytest.mark.asyncio
async def test_successful_preflight_is_recorded_in_run_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = FakeModel()
    settings = Settings(_env_file=None, openai_api_key="test")
    preflight.clear_preflight_cache()
    monkeypatch.setattr(
        preflight,
        "build_tier_models",
        lambda _: {tier: SimpleNamespace(model=model) for tier in ("low", "mid", "high")},
    )
    monkeypatch.setattr(
        preflight,
        "tier_spec",
        lambda _settings, _tier: SimpleNamespace(
            provider="openai",
            name="budgeted-model",
            price_in=1.0,
            price_out=6.0,
        ),
    )
    tracker = _budget()

    await preflight.preflight_tier_models(
        settings,
        ("low",),
        budget_tracker=tracker,
    )

    snapshot = tracker.snapshot()
    assert model.calls == 1
    assert snapshot.model_calls == 1
    assert snapshot.by_call_kind["preflight:openai:budgeted-model"]["model_calls"] == 1


def test_required_tiers_cover_grader_escalation_override_and_subagents() -> None:
    settings = Settings(
        _env_file=None,
        harness_enable_rubric=False,
        harness_max_continuations=1,
    )

    assert preflight.required_preflight_tiers(settings) == ("low",)
    assert preflight.required_preflight_tiers(
        settings, model_override="high", subagent_tiers=["mid"]
    ) == ("low", "mid", "high")
