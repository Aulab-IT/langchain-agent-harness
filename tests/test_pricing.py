from __future__ import annotations

from decimal import Decimal

from langchain_core.messages import AIMessage

from agent_harness.pricing import (
    ModelCallUsage,
    PriceEntry,
    PricingCatalog,
    aggregate_run_usage,
    build_call_usage,
    catalog_from_settings,
    compute_costs,
    extract_token_counts,
)
from agent_harness.usage import token_metrics


def _catalog() -> PricingCatalog:
    return PricingCatalog(
        [
            PriceEntry(
                provider="openai",
                model="gpt-x",
                input_price=Decimal("1.0"),
                output_price=Decimal("6.0"),
                cached_input_price=Decimal("0.25"),
                version="v1",
            )
        ]
    )


def test_cost_is_decimal_not_float() -> None:
    # 0.1 + 0.2 in float non fa 0.3: il costo deve restare esatto.
    price = PriceEntry(
        provider="p", model="m", input_price=Decimal("0.1"), output_price=Decimal("0.2")
    )
    input_cost, output_cost, _ = compute_costs(
        input_tokens=1_000_000,
        cached_input_tokens=0,
        output_tokens=1_000_000,
        reasoning_tokens=0,
        price=price,
    )
    assert input_cost == Decimal("0.1")
    assert output_cost == Decimal("0.2")
    assert input_cost + output_cost == Decimal("0.3")


def test_cached_input_priced_separately() -> None:
    price = _catalog().resolve("openai", "gpt-x")
    assert price is not None
    input_cost, _, _ = compute_costs(
        input_tokens=1_000_000,
        cached_input_tokens=400_000,
        output_tokens=0,
        reasoning_tokens=0,
        price=price,
    )
    # 600k non-cache a 1.0/M + 400k cache a 0.25/M = 0.6 + 0.1 = 0.7
    assert input_cost == Decimal("0.7")


def test_extract_token_counts_reads_details() -> None:
    counts = extract_token_counts(
        {
            "input_tokens": 100,
            "output_tokens": 40,
            "input_token_details": {"cache_read": 30},
            "output_token_details": {"reasoning": 12},
        }
    )
    assert counts == {
        "input_tokens": 100,
        "cached_input_tokens": 30,
        "output_tokens": 40,
        "reasoning_tokens": 12,
    }


def test_build_call_usage_absent_when_no_provider_usage() -> None:
    usage = build_call_usage(
        provider="openai",
        model="gpt-x",
        execution_kind="cloud",
        usage_metadata=None,
        catalog=_catalog(),
    )
    assert usage.usage_source == "absent"
    assert usage.total_cost == Decimal(0)


def test_build_call_usage_computes_cost_and_version() -> None:
    usage = build_call_usage(
        provider="openai",
        model="gpt-x",
        execution_kind="cloud",
        usage_metadata={"input_tokens": 1_000_000, "output_tokens": 500_000},
        catalog=_catalog(),
    )
    assert usage.pricing_version == "v1"
    assert usage.input_cost == Decimal("1.0")
    assert usage.output_cost == Decimal("3.0")
    assert usage.total_cost == Decimal("4.0")
    assert usage.total_tokens == 1_500_000


def test_local_execution_is_not_free_but_billed_zero() -> None:
    usage = ModelCallUsage(
        provider="ollama",
        model="local",
        execution_kind="local",
        input_tokens=1000,
        output_tokens=500,
        effective_local_cost=Decimal("0.002"),
    )
    assert usage.total_cost == Decimal(0)  # nessuna fattura API
    assert usage.effective_local_cost == Decimal("0.002")  # ma non gratis


def test_aggregate_separates_context_from_cumulative() -> None:
    calls = [
        ModelCallUsage(provider="openai", model="m", execution_kind="cloud",
                       input_tokens=100, output_tokens=20),
        ModelCallUsage(provider="openai", model="m", execution_kind="cloud",
                       input_tokens=300, output_tokens=30),
    ]
    summary = aggregate_run_usage(calls)
    assert summary.context_input_tokens == 300  # ultima chiamata
    assert summary.cumulative_input_tokens == 400  # somma
    assert summary.cumulative_output_tokens == 50
    assert summary.calls == 2


def test_pricing_resolves_latest_overlapping_entry() -> None:
    catalog = PricingCatalog(
        [
            PriceEntry(provider="p", model="m", input_price=Decimal("1"),
                       output_price=Decimal("2"), version="old", valid_from="2026-01-01"),
            PriceEntry(provider="p", model="m", input_price=Decimal("3"),
                       output_price=Decimal("4"), version="new", valid_from="2026-06-01"),
        ]
    )
    entry = catalog.resolve("p", "m", when="2026-07-01")
    assert entry is not None
    assert entry.version == "new"


def test_pricing_respects_validity_window() -> None:
    catalog = PricingCatalog(
        [
            PriceEntry(provider="p", model="m", input_price=Decimal("1"),
                       output_price=Decimal("2"), version="v1",
                       valid_from="2026-01-01", valid_to="2026-06-01"),
        ]
    )
    assert catalog.resolve("p", "m", when="2026-07-01") is None
    assert catalog.resolve("p", "m", when="2026-03-01") is not None


def test_token_metrics_from_messages() -> None:
    messages = [
        AIMessage(
            content="a",
            usage_metadata={"input_tokens": 100, "output_tokens": 10, "total_tokens": 110},
        ),
        AIMessage(
            content="b",
            usage_metadata={
                "input_tokens": 250,
                "output_tokens": 20,
                "total_tokens": 270,
                "output_token_details": {"reasoning": 5},
            },
        ),
    ]
    metrics = token_metrics(messages)
    assert metrics["context_input_tokens"] == 250
    assert metrics["cumulative_input_tokens"] == 350
    assert metrics["cumulative_output_tokens"] == 30
    assert metrics["reasoning_tokens"] == 5


def test_catalog_from_settings_seeds_tiers() -> None:
    from agent_harness.config import Settings

    settings = Settings(openai_api_key="x")
    catalog = catalog_from_settings(settings)
    entry = catalog.resolve("openai", settings.openai_model_low)
    assert entry is not None
    assert entry.input_price == Decimal(str(settings.openai_price_in_low))
