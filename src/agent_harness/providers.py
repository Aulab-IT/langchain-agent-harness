"""Astrazione dei provider di modelli (Fase 2 del piano evolutivo).

La factory importava ``ChatOpenAI`` direttamente e assumeva ovunque le sue capacità:
Responses API, reasoning cifrato, usage reporting. Aggiungere un provider locale (Ollama,
MLX) significava sparpagliare `if openai` per il codice. Qui il provider diventa un
contratto esplicito — capacità dichiarate, usage normalizzato, tassonomia degli errori — e
gli adattatori vivono ai bordi.

Principio guida (§6.7 del piano): **non ridurre il provider a una stringa ``model_name``.**
L'astrazione copre capacità, usage, pricing, errori, tool calling, structured output,
reasoning, caching e streaming. Un provider OpenAI-compatibile non è equivalente a OpenAI
solo perché espone ``/v1``: le differenze si dichiarano nelle capability e si verificano con
un capability probe, non si danno per scontate.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Literal, Protocol, runtime_checkable

from langchain_core.language_models.chat_models import BaseChatModel

from agent_harness.pricing import ExecutionKind, ModelCallUsage, PricingCatalog, build_call_usage

ProviderErrorKind = Literal[
    "rate_limit",
    "timeout",
    "auth",
    "context_length",
    "unavailable",
    "bad_request",
    "unknown",
]


@dataclass(frozen=True)
class ModelCapabilities:
    """Cosa sa fare un modello. Dichiarato, non indovinato dal nome.

    Un routing che manda structured output a un modello che non lo supporta fallisce a
    metà run; qui la capacità è nota a startup e la si può rifiutare prima di partire.
    """

    context_window: int
    max_output_tokens: int
    supports_tools: bool = True
    supports_parallel_tools: bool = False
    supports_structured_output: bool = False
    supports_reasoning: bool = False
    supports_prompt_caching: bool = False
    supports_encrypted_reasoning: bool = False
    supports_usage_reporting: bool = True
    supports_model_listing: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "context_window": self.context_window,
            "max_output_tokens": self.max_output_tokens,
            "supports_tools": self.supports_tools,
            "supports_parallel_tools": self.supports_parallel_tools,
            "supports_structured_output": self.supports_structured_output,
            "supports_reasoning": self.supports_reasoning,
            "supports_prompt_caching": self.supports_prompt_caching,
            "supports_encrypted_reasoning": self.supports_encrypted_reasoning,
            "supports_usage_reporting": self.supports_usage_reporting,
            "supports_model_listing": self.supports_model_listing,
        }


# Profilo di capacità dei modelli OpenAI usati dall'harness (scala gpt-5.6-*): Responses API,
# reasoning cifrato, prompt caching e usage completo. È il riferimento contro cui i provider
# locali si misurano col conformance probe.
OPENAI_CAPABILITIES = ModelCapabilities(
    context_window=128_000,
    max_output_tokens=64_000,
    supports_tools=True,
    supports_parallel_tools=True,
    supports_structured_output=True,
    supports_reasoning=True,
    supports_prompt_caching=True,
    supports_encrypted_reasoning=True,
    supports_usage_reporting=True,
    supports_model_listing=True,
)

# Profilo di capacità dei modelli Claude (Anthropic). Finestra ampia, tool calling e
# structured output nativi, reasoning adattivo; niente reasoning cifrato in stile OpenAI
# Responses. Prezzi e id modello stanno in Settings (Fase 0), qui solo le capacità.
ANTHROPIC_CAPABILITIES = ModelCapabilities(
    context_window=200_000,
    max_output_tokens=8_192,
    supports_tools=True,
    supports_parallel_tools=True,
    supports_structured_output=True,
    supports_reasoning=True,
    supports_prompt_caching=True,
    supports_encrypted_reasoning=False,
    supports_usage_reporting=True,
    supports_model_listing=True,
)

# I provider locali (Ollama, MLX) partono da capacità conservative: reasoning cifrato e
# prompt caching assenti, structured output/usage da verificare per endpoint e modello.
# Deny-by-default: si abilita una capacità solo dopo che il probe l'ha confermata.
LOCAL_CAPABILITIES = ModelCapabilities(
    context_window=8_192,
    max_output_tokens=2_048,
    supports_tools=True,
    supports_parallel_tools=False,
    supports_structured_output=False,
    supports_reasoning=False,
    supports_prompt_caching=False,
    supports_encrypted_reasoning=False,
    supports_usage_reporting=False,
    supports_model_listing=True,
)


@dataclass(frozen=True)
class ModelDescriptor:
    """Identità di un modello indipendente dal vendor: provider, nome, capacità, listino.

    ``pricing_key`` collega il descriptor al catalogo prezzi (Fase 0) ed è distinto dal nome
    vendor, così un alias di config non deve coincidere col nome tecnico del modello.
    """

    provider: str
    model: str
    capabilities: ModelCapabilities
    execution_kind: ExecutionKind = "cloud"
    pricing_key: str = ""
    reasoning_effort: str = "low"

    def resolved_pricing_key(self) -> str:
        return self.pricing_key or self.model


@dataclass(frozen=True)
class BuildOptions:
    """Parametri di costruzione del modello che non appartengono al descriptor."""

    api_key: str | None = None
    base_url: str | None = None
    timeout: int = 120
    max_retries: int = 3
    # Cap di output per i provider che lo richiedono esplicito (Anthropic): tetto per
    # risposta, non finestra del modello. 8192 è un default prudente per l'harness.
    max_output_tokens: int = 8192


class ProviderError(Exception):
    """Errore di provider normalizzato in una tassonomia comune.

    Il codice del runner reagisce al ``kind`` (retry su ``rate_limit``/``timeout``,
    escalation su ``context_length``, stop su ``auth``) senza conoscere le eccezioni
    specifiche di ciascun SDK.
    """

    def __init__(self, kind: ProviderErrorKind, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.kind = kind
        self.retryable = retryable


@runtime_checkable
class ModelProvider(Protocol):
    """Contratto che ogni adattatore di provider implementa."""

    name: str

    def build_chat_model(
        self, descriptor: ModelDescriptor, options: BuildOptions
    ) -> BaseChatModel: ...

    def normalize_usage(
        self,
        descriptor: ModelDescriptor,
        usage_metadata: dict[str, Any] | None,
        catalog: PricingCatalog,
    ) -> ModelCallUsage: ...

    def classify_error(self, exc: Exception) -> ProviderError: ...


def _classify_by_text(exc: Exception) -> ProviderError:
    """Fallback comune: mappa un'eccezione al tipo canonico leggendo messaggio e nome classe.

    Non conosce gli SDK specifici; gli adattatori possono raffinare, ma questo copre i casi
    ricorrenti (429, timeout, 401/403, context length) per qualunque provider HTTP.
    """
    text = f"{type(exc).__name__} {exc}".lower()
    if "rate limit" in text or "429" in text or "too many requests" in text:
        return ProviderError("rate_limit", str(exc), retryable=True)
    if "timeout" in text or "timed out" in text:
        return ProviderError("timeout", str(exc), retryable=True)
    if "context length" in text or "maximum context" in text or "context_length" in text:
        return ProviderError("context_length", str(exc), retryable=False)
    if "unauthorized" in text or "401" in text or "403" in text or "api key" in text:
        return ProviderError("auth", str(exc), retryable=False)
    if "connection" in text or "unavailable" in text or "503" in text or "502" in text:
        return ProviderError("unavailable", str(exc), retryable=True)
    if "400" in text or "bad request" in text or "invalid" in text:
        return ProviderError("bad_request", str(exc), retryable=False)
    return ProviderError("unknown", str(exc), retryable=False)


class _BaseAdapter:
    """Parti condivise: normalize_usage delega alla Fase 0, classify_error al fallback testo."""

    name = "base"
    execution_kind: ExecutionKind = "cloud"

    def normalize_usage(
        self,
        descriptor: ModelDescriptor,
        usage_metadata: dict[str, Any] | None,
        catalog: PricingCatalog,
    ) -> ModelCallUsage:
        return build_call_usage(
            provider=descriptor.provider,
            model=descriptor.resolved_pricing_key(),
            execution_kind=descriptor.execution_kind,
            usage_metadata=usage_metadata,
            catalog=catalog,
        )

    def classify_error(self, exc: Exception) -> ProviderError:
        return _classify_by_text(exc)


class OpenAIProviderAdapter(_BaseAdapter):
    """Adattatore OpenAI: preserva esattamente il comportamento della factory precedente.

    Responses API, ``store=False``, reasoning cifrato incluso, retry e timeout: identici a
    ``factory._openai_model``, così migrare a questo adattatore non cambia il runtime.
    """

    name = "openai"
    execution_kind = "cloud"

    def build_chat_model(
        self, descriptor: ModelDescriptor, options: BuildOptions
    ) -> BaseChatModel:
        # Import locale: è l'unico punto dell'harness che dipende da langchain_openai, così
        # la factory non lo importa più direttamente (criterio di accettazione §6.9).
        from langchain_openai import ChatOpenAI
        from pydantic import SecretStr

        if not options.api_key:
            raise ProviderError("auth", "OPENAI_API_KEY non configurata.", retryable=False)
        return ChatOpenAI(
            model=descriptor.model,
            api_key=SecretStr(options.api_key),
            reasoning_effort=descriptor.reasoning_effort,
            use_responses_api=True,
            store=False,
            include=["reasoning.encrypted_content"],
            max_retries=options.max_retries,
            timeout=options.timeout,
        )


class AnthropicProviderAdapter(_BaseAdapter):
    """Adattatore Claude (Anthropic) tramite ``langchain_anthropic.ChatAnthropic``.

    Resta nel pattern degli altri adapter: costruisce un ``BaseChatModel`` che il grafo e i
    middleware consumano senza sapere quale vendor c'è dietro. Non passa ``temperature``
    (rimossa sui modelli Claude correnti come Opus 4.8) né un ``thinking`` esplicito: il
    reasoning adattivo dei modelli recenti si attiva da sé e passarlo cablato rischierebbe un
    400 su versioni diverse di langchain_anthropic. ``max_tokens`` è un tetto per risposta,
    non la finestra del modello.
    """

    name = "anthropic"
    execution_kind = "cloud"

    def build_chat_model(
        self, descriptor: ModelDescriptor, options: BuildOptions
    ) -> BaseChatModel:
        from langchain_anthropic import ChatAnthropic
        from pydantic import SecretStr

        if not options.api_key:
            raise ProviderError("auth", "ANTHROPIC_API_KEY non configurata.", retryable=False)
        # `model`/`max_tokens` sono i nomi campo accettati a runtime (populate_by_name); il
        # plugin mypy di pydantic vede solo i loro alias, da qui l'ignore mirato.
        return ChatAnthropic(  # type: ignore[call-arg]
            model=descriptor.model,
            api_key=SecretStr(options.api_key),
            max_tokens=options.max_output_tokens,
            timeout=float(options.timeout),
            max_retries=options.max_retries,
        )


class _OpenAICompatibleLocalAdapter(_BaseAdapter):
    """Base per provider locali che espongono un'API compatibile con Chat Completions.

    Usa ``ChatOpenAI`` puntato a un ``base_url`` locale, ma senza le opzioni specifiche di
    OpenAI (Responses API, reasoning cifrato) che un server locale in genere non implementa:
    darle per scontate è l'errore che il piano avverte di non fare.
    """

    execution_kind = "local"
    default_base_url = "http://127.0.0.1:8080/v1"

    def build_chat_model(
        self, descriptor: ModelDescriptor, options: BuildOptions
    ) -> BaseChatModel:
        from langchain_openai import ChatOpenAI
        from pydantic import SecretStr

        base_url = options.base_url or self.default_base_url
        return ChatOpenAI(
            model=descriptor.model,
            # I server locali non richiedono chiave ma ChatOpenAI ne vuole una non vuota.
            api_key=SecretStr(options.api_key or "local-no-key"),
            base_url=base_url,
            max_retries=options.max_retries,
            timeout=options.timeout,
        )


class OllamaProviderAdapter(_OpenAICompatibleLocalAdapter):
    """Ollama via il suo endpoint OpenAI-compatibile ``/v1``.

    Esecuzione locale: nessuna fattura API. Ollama espone usage su alcuni endpoint; finché
    il probe non lo conferma, ``supports_usage_reporting`` resta ``False`` e l'usage sarà
    marcato ``absent`` invece di inventare token."""

    name = "ollama"
    default_base_url = "http://127.0.0.1:11434/v1"


class MLXProviderAdapter(_OpenAICompatibleLocalAdapter):
    """MLX LM server su Apple Silicon (endpoint tipo Chat Completions).

    Il server MLX incluso offre solo controlli di sicurezza basilari: va tenuto in loopback e
    in sviluppo, mai esposto direttamente. Lo scheduling su host Apple Silicon lo verifica il
    placement del routing (Fase 2/3), non questo adattatore.
    """

    name = "mlx"
    default_base_url = "http://127.0.0.1:8080/v1"


class ConformanceProviderAdapter(_BaseAdapter):
    """Adattatore fittizio deterministico, per testare i failure path senza rete né token.

    Restituisce un modello che risponde in modo fisso e non chiama alcuna API. Serve alla
    conformance suite: verifica che registry, routing e normalizzazione usage funzionino con
    un provider qualunque, e permette di iniettare errori a comando.
    """

    name = "conformance"
    execution_kind = "cloud"

    def __init__(self, *, fail_with: Exception | None = None) -> None:
        self._fail_with = fail_with

    def build_chat_model(
        self, descriptor: ModelDescriptor, options: BuildOptions
    ) -> BaseChatModel:
        from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
        from langchain_core.messages import AIMessage

        return GenericFakeChatModel(messages=iter([AIMessage(content="conformance-ok")]))

    def classify_error(self, exc: Exception) -> ProviderError:
        return _classify_by_text(exc)


class ProviderRegistry:
    """Mappa nome-provider → adattatore, e costruisce il modello da un descriptor.

    Rimuove il ``ChatOpenAI`` cablato nella factory: ogni ruolo (tier, grader, reviewer,
    researcher) chiede al registry il modello del proprio descriptor, e il vendor resta
    confinato all'adattatore.
    """

    def __init__(self) -> None:
        self._providers: dict[str, ModelProvider] = {}

    def register(self, provider: ModelProvider) -> None:
        self._providers[provider.name] = provider

    def get(self, name: str) -> ModelProvider:
        try:
            return self._providers[name]
        except KeyError:
            raise ProviderError(
                "bad_request", f"Provider non registrato: {name}", retryable=False
            ) from None

    def names(self) -> list[str]:
        return sorted(self._providers)

    def build(self, descriptor: ModelDescriptor, options: BuildOptions) -> BaseChatModel:
        return self.get(descriptor.provider).build_chat_model(descriptor, options)

    def normalize_usage(
        self,
        descriptor: ModelDescriptor,
        usage_metadata: dict[str, Any] | None,
        catalog: PricingCatalog,
    ) -> ModelCallUsage:
        return self.get(descriptor.provider).normalize_usage(descriptor, usage_metadata, catalog)


def default_registry() -> ProviderRegistry:
    """Registry con gli adattatori standard: OpenAI, Anthropic (Claude) e i due locali."""
    registry = ProviderRegistry()
    registry.register(OpenAIProviderAdapter())
    registry.register(AnthropicProviderAdapter())
    registry.register(OllamaProviderAdapter())
    registry.register(MLXProviderAdapter())
    return registry


def openai_descriptor(model: str, *, reasoning_effort: str = "low") -> ModelDescriptor:
    """Descriptor per un modello OpenAI dell'harness, con il profilo di capacità noto."""
    return ModelDescriptor(
        provider="openai",
        model=model,
        capabilities=OPENAI_CAPABILITIES,
        execution_kind="cloud",
        pricing_key=model,
        reasoning_effort=reasoning_effort,
    )


def anthropic_descriptor(model: str, *, reasoning_effort: str = "low") -> ModelDescriptor:
    """Descriptor per un modello Claude, con il profilo di capacità Anthropic."""
    return ModelDescriptor(
        provider="anthropic",
        model=model,
        capabilities=ANTHROPIC_CAPABILITIES,
        execution_kind="cloud",
        pricing_key=model,
        reasoning_effort=reasoning_effort,
    )


def local_descriptor(provider: str, model: str) -> ModelDescriptor:
    """Descriptor per un modello locale (Ollama o MLX): esecuzione locale, capacità prudenti."""
    return ModelDescriptor(
        provider=provider,
        model=model,
        capabilities=LOCAL_CAPABILITIES,
        execution_kind="local",
        pricing_key=model,
    )


@dataclass(frozen=True)
class CapabilityProbeResult:
    """Esito di un capability probe: capacità dichiarate e (se eseguito live) verificate.

    Il probe live richiede rete e va oltre i test offline; questa struttura è ciò che il
    probe popola, e permette al routing di rifiutare a startup una capacità mancante.
    """

    descriptor: ModelDescriptor
    declared: ModelCapabilities
    verified: dict[str, bool]

    def unsupported(self, capability: str) -> bool:
        return self.verified.get(capability) is False


def declared_probe(descriptor: ModelDescriptor) -> CapabilityProbeResult:
    """Probe offline: riporta le capacità dichiarate senza contattare l'endpoint.

    È il punto di partenza deny-by-default; un probe live sostituirà i valori ``verified``
    con l'esito reale per singolo modello/endpoint.
    """
    return CapabilityProbeResult(
        descriptor=descriptor,
        declared=descriptor.capabilities,
        verified={},
    )


def with_capabilities(
    descriptor: ModelDescriptor, capabilities: ModelCapabilities
) -> ModelDescriptor:
    return replace(descriptor, capabilities=capabilities)
