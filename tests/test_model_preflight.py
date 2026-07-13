from types import SimpleNamespace
from typing import Any

import pytest
from langchain_core.messages import AIMessage

import agent_harness.model_preflight as preflight
from agent_harness.config import Settings
from agent_harness.model_preflight import ModelPreflightError


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
