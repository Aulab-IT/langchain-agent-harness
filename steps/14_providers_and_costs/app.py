"""Step 14: provider-neutral model catalog, capability gate e costo normalizzato."""

from decimal import Decimal

from agent_harness.pricing import PriceEntry, PricingCatalog
from agent_harness.providers import (
    BuildOptions,
    ProviderError,
    default_registry,
    local_descriptor,
    openai_descriptor,
)


def main() -> None:
    registry = default_registry()
    cloud = openai_descriptor("gpt-demo", reasoning_effort="low")
    local = local_descriptor("ollama", "qwen-demo")
    catalog = PricingCatalog(
        [
            PriceEntry(
                provider="openai",
                model="gpt-demo",
                input_price=Decimal("1"),
                output_price=Decimal("6"),
                version="lesson",
            )
        ]
    )

    print("Provider registrati:", ", ".join(registry.names()))
    print("Cloud structured output:", cloud.capabilities.supports_structured_output)
    print("Locale structured output:", local.capabilities.supports_structured_output)
    usage = registry.get("openai").normalize_usage(
        cloud,
        {"input_tokens": 1_000, "output_tokens": 250, "total_tokens": 1_250},
        catalog,
    )
    print("Costo normalizzato demo: $", usage.total_cost)

    try:
        registry.build(cloud, BuildOptions(api_key=None))
    except ProviderError as error:
        print("Preflight senza chiave:", error.kind, "retryable=", error.retryable)


if __name__ == "__main__":
    main()
