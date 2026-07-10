"""Gestione esplicita di contesto e token (Fase 1 del piano evolutivo).

Prima di questo modulo ``HARNESS_CONTEXT_WINDOW`` era un numero mostrato in UI e mai
applicato: nessun budget, nessuna compaction prevedibile, la finestra si riempiva finché
il provider non rifiutava. Qui il budget diventa un oggetto che si ispeziona e su cui si
decide, con azioni deterministiche e un ordine di riduzione stabile.

Il componente è provider-neutral: prende la dimensione della finestra come parametro (la
fornisce il descriptor del modello, Fase 2) e non conosce nessun vendor. È logica pura su
liste di messaggi, quindi interamente testabile offline, senza chiamare un modello.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

from langchain_core.messages import BaseMessage, ToolMessage

from agent_harness.usage import token_estimate


class ContextAction(StrEnum):
    """Cosa fare quando si ispeziona il contesto, in ordine di aggressività crescente."""

    KEEP = "keep"
    OFFLOAD_TOOL_OUTPUT = "offload_tool_output"
    SUMMARIZE_HISTORY = "summarize_history"
    DROP_RECONSTRUCTIBLE_EVENTS = "drop_reconstructible_events"
    START_FRESH_CONTINUATION = "start_fresh_continuation"
    REJECT_OVER_BUDGET = "reject_over_budget"


@dataclass(frozen=True)
class ContextBudget:
    """Soglie del budget di contesto per un run.

    ``reserved_output_tokens`` è lo spazio tenuto libero per la risposta: la finestra
    utile è ``max_tokens - reserved_output_tokens``. ``warning_ratio`` e
    ``compaction_ratio`` sono frazioni di quella finestra utile.
    """

    max_tokens: int
    reserved_output_tokens: int = 4_000
    warning_ratio: float = 0.7
    compaction_ratio: float = 0.8
    hard_ratio: float = 0.95

    @property
    def usable_tokens(self) -> int:
        return max(1, self.max_tokens - self.reserved_output_tokens)


@dataclass(frozen=True)
class ContextSnapshot:
    """Fotografia del contesto: quanti token, come sono distribuiti, quanto è pieno."""

    total_tokens: int
    usable_tokens: int
    fill_ratio: float
    tool_output_tokens: int
    history_tokens: int
    reconstructible_tokens: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# Marcatore di un output di tool già scaricato su file: se lo ritroviamo in un messaggio
# non lo consideriamo più "lungo", altrimenti la compaction lo offloaderebbe all'infinito.
OFFLOAD_MARKER = "[tool-output-offloaded]"


class ContextBudgetManager:
    """Ispeziona il contesto e decide l'azione, senza eseguirla.

    Separare la decisione dall'esecuzione rende la politica testabile in isolamento e
    permette al runner di emettere l'azione come evento prima di applicarla.
    """

    def __init__(self, *, tool_output_soft_limit: int = 4_000) -> None:
        self.tool_output_soft_limit = tool_output_soft_limit

    def inspect(self, messages: list[BaseMessage], budget: ContextBudget) -> ContextSnapshot:
        total = 0
        tool_output = 0
        history = 0
        reconstructible = 0
        for message in messages:
            size = token_estimate(_content_text(message))
            total += size
            if isinstance(message, ToolMessage):
                tool_output += size
                if size > _estimate_limit(self.tool_output_soft_limit) and not _is_offloaded(
                    message
                ):
                    reconstructible += size
            else:
                history += size
        fill = round(total / budget.usable_tokens, 4)
        return ContextSnapshot(
            total_tokens=total,
            usable_tokens=budget.usable_tokens,
            fill_ratio=fill,
            tool_output_tokens=tool_output,
            history_tokens=history,
            reconstructible_tokens=reconstructible,
        )

    def decide(self, snapshot: ContextSnapshot, budget: ContextBudget) -> ContextAction:
        """Sceglie l'azione minima sufficiente a rientrare nel budget.

        Ordine di riduzione: prima si scaricano gli output di tool lunghi (recupero grande
        a informazione zero persa, il file resta), poi si riassume la storia, infine — se
        neanche questo basta — si apre una continuazione fresca. Il rifiuto è l'ultima
        risorsa e scatta solo se il solo prompt di sistema già sfora.
        """
        ratio = snapshot.fill_ratio
        if ratio < budget.warning_ratio:
            return ContextAction.KEEP
        if ratio < budget.compaction_ratio:
            # In zona warning si interviene solo se c'è un recupero facile da fare.
            if snapshot.reconstructible_tokens > 0:
                return ContextAction.OFFLOAD_TOOL_OUTPUT
            return ContextAction.KEEP
        # Oltre la soglia di compaction: si riduce davvero.
        if snapshot.reconstructible_tokens > 0:
            return ContextAction.OFFLOAD_TOOL_OUTPUT
        if snapshot.history_tokens > snapshot.usable_tokens // 2:
            return ContextAction.SUMMARIZE_HISTORY
        if ratio >= budget.hard_ratio:
            # Neanche riducendo si rientra e non c'è nulla di comprimibile: meglio una
            # continuazione fresca che sbattere contro il rifiuto del provider a metà run.
            if snapshot.history_tokens <= _content_text_floor():
                return ContextAction.REJECT_OVER_BUDGET
            return ContextAction.START_FRESH_CONTINUATION
        return ContextAction.SUMMARIZE_HISTORY


def _content_text_floor() -> int:
    # Se la storia è quasi solo prompt di sistema non c'è niente da comprimere.
    return 200


def _estimate_limit(char_limit: int) -> int:
    # token_estimate divide i caratteri per 4; il soft-limit è espresso in token.
    return char_limit


def _content_text(message: BaseMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    parts = [
        str(block.get("text", ""))
        for block in content
        if isinstance(block, dict) and block.get("type") == "text"
    ]
    return " ".join(parts)


def _is_offloaded(message: BaseMessage) -> bool:
    return OFFLOAD_MARKER in _content_text(message)


@dataclass(frozen=True)
class OffloadedOutput:
    """Sostituto compatto di un output di tool lungo: riferimento, checksum, estratto.

    Il contenuto integrale resta su file nel workspace; nel contesto entra solo questo,
    così il modello sa che il dato esiste e come recuperarlo senza pagarne i token ogni turno.
    """

    reference: str
    checksum: str
    excerpt: str
    original_tokens: int

    def render(self) -> str:
        return (
            f"{OFFLOAD_MARKER} ref={self.reference} sha256={self.checksum} "
            f"(~{self.original_tokens} token). Estratto:\n{self.excerpt}"
        )


def offload_tool_output(
    content: str, *, reference: str, excerpt_chars: int = 500
) -> OffloadedOutput:
    """Costruisce il sostituto compatto di un output lungo.

    Il checksum lega il riferimento al contenuto esatto: se il file cambia, il checksum non
    combacia più e il modello sa che l'estratto potrebbe non riflettere l'originale.
    """
    checksum = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
    excerpt = content[:excerpt_chars]
    if len(content) > excerpt_chars:
        excerpt += "…"
    return OffloadedOutput(
        reference=reference,
        checksum=checksum,
        excerpt=excerpt,
        original_tokens=token_estimate(content),
    )


def drop_reconstructible(messages: list[BaseMessage]) -> list[BaseMessage]:
    """Rimuove output di tool duplicati consecutivi per lo stesso tool call id.

    Un tool idempotente riletto (stesso ``tool_call_id``) non aggiunge informazione: si
    tiene solo l'ultima osservazione. Deterministico e senza perdita: gli altri messaggi
    passano invariati.
    """
    seen: set[str] = set()
    kept: list[BaseMessage] = []
    for message in reversed(messages):
        if isinstance(message, ToolMessage):
            key = message.tool_call_id
            if key in seen:
                continue
            seen.add(key)
        kept.append(message)
    kept.reverse()
    return kept


@dataclass
class StructuredSummary:
    """Riassunto strutturato di turni chiusi: si preserva ciò che serve al proseguo.

    Obiettivo, vincoli, decisioni, errori aperti e prove non si buttano mai; le chiacchiere
    intermedie sì. Lo schema è quello del piano (§5.3) così la UI può renderizzarlo e il
    modello ricostruire lo stato senza rileggere l'intera storia.
    """

    goal: str = ""
    constraints: list[str] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)
    completed: list[str] = field(default_factory=list)
    open_items: list[str] = field(default_factory=list)
    artifacts: list[dict[str, str]] = field(default_factory=list)
    verification: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def render(self) -> str:
        lines = [f"goal: {self.goal}"]
        for name, values in (
            ("constraints", self.constraints),
            ("decisions", self.decisions),
            ("completed", self.completed),
            ("open_items", self.open_items),
            ("verification", self.verification),
            ("failures", self.failures),
        ):
            if values:
                lines.append(f"{name}:")
                lines.extend(f"  - {value}" for value in values)
        if self.artifacts:
            lines.append("artifacts:")
            for artifact in self.artifacts:
                lines.append(f"  - path: {artifact.get('path', '')}")
                if artifact.get("checksum"):
                    lines.append(f"    checksum: {artifact['checksum']}")
        return "\n".join(lines)


def context_budget_from_settings(settings: Any) -> ContextBudget:
    """Costruisce il budget dai valori di ``Settings``, rendendo ``harness_context_window``
    un limite realmente applicato invece di un semplice metadato mostrato in UI."""
    return ContextBudget(
        max_tokens=int(settings.harness_context_window),
        reserved_output_tokens=int(getattr(settings, "harness_reserved_output_tokens", 4_000)),
        warning_ratio=float(getattr(settings, "harness_context_warning_ratio", 0.7)),
        compaction_ratio=float(getattr(settings, "harness_context_compaction_ratio", 0.8)),
    )


class LiveUsageThrottle:
    """Lascia passare al massimo un evento ``usage.live`` per finestra temporale.

    Ogni frammento di streaming generava una scrittura ``usage.live``: ~33k eventi per la
    sola live in un giro d'uso, la principale causa di write amplification del control DB
    (§9.2 dell'analisi). Qui si tiene l'ultimo valore e si emette al più una volta al secondo;
    l'ultimo valore reale si forza sempre con ``flush``.
    """

    def __init__(self, *, min_interval_seconds: float = 1.0) -> None:
        self.min_interval_seconds = min_interval_seconds
        self._last_emit: float | None = None
        self._pending: dict[str, Any] | None = None

    def offer(self, payload: dict[str, Any], *, now: float) -> dict[str, Any] | None:
        """Registra un aggiornamento; restituisce il payload da emettere o ``None``."""
        self._pending = payload
        if self._last_emit is None or (now - self._last_emit) >= self.min_interval_seconds:
            self._last_emit = now
            self._pending = None
            return payload
        return None

    def flush(self) -> dict[str, Any] | None:
        """Emette l'ultimo valore trattenuto, se c'è: chiude il run senza perdere il finale."""
        if self._pending is None:
            return None
        payload = self._pending
        self._pending = None
        return payload


__all__ = [
    "ContextAction",
    "ContextBudget",
    "ContextBudgetManager",
    "ContextSnapshot",
    "LiveUsageThrottle",
    "OffloadedOutput",
    "StructuredSummary",
    "context_budget_from_settings",
    "drop_reconstructible",
    "offload_tool_output",
]
