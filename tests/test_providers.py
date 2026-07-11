from __future__ import annotations

from decimal import Decimal

import pytest
from langchain_core.language_models.chat_models import BaseChatModel

from agent_harness.pricing import PriceEntry, PricingCatalog
from agent_harness.providers import (
    ANTHROPIC_CAPABILITIES,
    LOCAL_CAPABILITIES,
    OPENAI_CAPABILITIES,
    AnthropicProviderAdapter,
    BuildOptions,
    ConformanceProviderAdapter,
    ModelDescriptor,
    OllamaProviderAdapter,
    OpenAIProviderAdapter,
    ProviderError,
    ProviderRegistry,
    anthropic_descriptor,
    declared_probe,
    default_registry,
    openai_descriptor,
)


def _catalog() -> PricingCatalog:
    return PricingCatalog(
        [
            PriceEntry(
                provider="openai",
                model="gpt-x",
                input_price=Decimal("1.0"),
                output_price=Decimal("6.0"),
                version="v1",
            )
        ]
    )


def test_registry_builds_openai_without_network() -> None:
    registry = default_registry()
    descriptor = openai_descriptor("gpt-x", reasoning_effort="low")
    model = registry.build(descriptor, BuildOptions(api_key="test-key"))
    assert isinstance(model, BaseChatModel)


def test_openai_build_requires_key() -> None:
    adapter = OpenAIProviderAdapter()
    descriptor = openai_descriptor("gpt-x")
    with pytest.raises(ProviderError) as excinfo:
        adapter.build_chat_model(descriptor, BuildOptions(api_key=None))
    assert excinfo.value.kind == "auth"


def test_registry_builds_anthropic_claude_without_network() -> None:
    registry = default_registry()
    assert "anthropic" in registry.names()
    descriptor = anthropic_descriptor("claude-opus-4-8")
    model = registry.build(descriptor, BuildOptions(api_key="test-key"))
    assert isinstance(model, BaseChatModel)


def test_anthropic_build_requires_key() -> None:
    adapter = AnthropicProviderAdapter()
    descriptor = anthropic_descriptor("claude-opus-4-8")
    with pytest.raises(ProviderError) as excinfo:
        adapter.build_chat_model(descriptor, BuildOptions(api_key=None))
    assert excinfo.value.kind == "auth"


def test_anthropic_normalizes_usage_with_catalog() -> None:
    adapter = AnthropicProviderAdapter()
    descriptor = anthropic_descriptor("claude-opus-4-8")
    catalog = PricingCatalog(
        [
            PriceEntry(
                provider="anthropic",
                model="claude-opus-4-8",
                input_price=Decimal("5.0"),
                output_price=Decimal("25.0"),
                version="v1",
            )
        ]
    )
    usage = adapter.normalize_usage(
        descriptor,
        {"input_tokens": 1_000_000, "output_tokens": 1_000_000, "total_tokens": 2_000_000},
        catalog,
    )
    assert usage.execution_kind == "cloud"
    assert usage.total_cost == Decimal("30.0")


def test_anthropic_capabilities_no_encrypted_reasoning() -> None:
    assert ANTHROPIC_CAPABILITIES.supports_reasoning is True
    assert ANTHROPIC_CAPABILITIES.supports_encrypted_reasoning is False


def test_unregistered_provider_raises() -> None:
    registry = ProviderRegistry()
    with pytest.raises(ProviderError) as excinfo:
        registry.get("nope")
    assert excinfo.value.kind == "bad_request"


def test_local_provider_normalizes_usage_as_local() -> None:
    adapter = OllamaProviderAdapter()
    descriptor = ModelDescriptor(
        provider="ollama",
        model="llama",
        capabilities=LOCAL_CAPABILITIES,
        execution_kind="local",
    )
    usage = adapter.normalize_usage(
        descriptor,
        {"input_tokens": 100, "output_tokens": 40, "total_tokens": 140},
        _catalog(),
    )
    assert usage.execution_kind == "local"
    # Nessun listino per ollama/llama: costo zero, ma usage_source resta 'provider'.
    assert usage.total_cost == Decimal(0)
    assert usage.usage_source == "provider"


def test_conformance_adapter_builds_fake_model() -> None:
    adapter = ConformanceProviderAdapter()
    descriptor = ModelDescriptor(
        provider="conformance", model="fake", capabilities=OPENAI_CAPABILITIES
    )
    model = adapter.build_chat_model(descriptor, BuildOptions())
    assert isinstance(model, BaseChatModel)


@pytest.mark.parametrize(
    ("message", "kind", "retryable"),
    [
        ("Error 429 rate limit exceeded", "rate_limit", True),
        ("Request timed out", "timeout", True),
        ("maximum context length is 8192", "context_length", False),
        ("401 Unauthorized: invalid api key", "auth", False),
        ("Connection refused, service unavailable", "unavailable", True),
    ],
)
def test_error_taxonomy(message: str, kind: str, retryable: bool) -> None:
    adapter = OpenAIProviderAdapter()
    error = adapter.classify_error(RuntimeError(message))
    assert error.kind == kind
    assert error.retryable is retryable


def test_declared_probe_is_deny_by_default() -> None:
    descriptor = ModelDescriptor(
        provider="ollama", model="llama", capabilities=LOCAL_CAPABILITIES, execution_kind="local"
    )
    result = declared_probe(descriptor)
    # Nessuna capacità è verificata finché un probe live non la conferma.
    assert result.verified == {}
    assert result.declared.supports_reasoning is False


def test_openai_capabilities_richer_than_local() -> None:
    assert OPENAI_CAPABILITIES.supports_encrypted_reasoning is True
    assert LOCAL_CAPABILITIES.supports_encrypted_reasoning is False
