"""Osservabilità del context engineering: rende visibile *quando* il contesto viene ridotto.

La compaction automatica esiste già — la fa il ``SummarizationMiddleware`` di deepagents, che
riassume la storia vecchia quando supera una frazione della finestra reale del modello. Ma è
invisibile: nessun evento, nessuna traccia. Questo middleware non compatta nulla; osserva. A
ogni chiamata al modello misura il contesto effettivo e ne emette una fotografia
(``context.snapshot``); quando i token effettivi crollano rispetto al picco del run — la firma
di una compaction appena avvenuta — emette ``context.compaction.detected`` con il prima/dopo.

La logica di misura è pura (``context_snapshot``, ``detect_compaction``) e testabile offline;
il middleware è il sottile strato che la collega al ciclo del modello e all'``event_callback``.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

from langchain.agents.middleware import (
    AgentMiddleware,
    ModelRequest,
    ModelResponse,
)
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage

from agent_harness.usage import token_estimate

EventSink = Callable[[dict[str, Any]], None]


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


def _category(message: BaseMessage) -> str:
    if isinstance(message, SystemMessage):
        return "System & memoria"
    if isinstance(message, (HumanMessage, AIMessage)):
        return "Conversazione"
    if isinstance(message, ToolMessage):
        return "Tool output"
    return "Altro"


@dataclass(frozen=True)
class ContextSnapshot:
    """Fotografia del contesto effettivo che entra in una chiamata al modello."""

    total_tokens: int
    window_tokens: int
    fill_ratio: float
    message_count: int
    categories: dict[str, int]

    def to_event(self) -> dict[str, Any]:
        return {
            "type": "context.snapshot",
            "total_tokens": self.total_tokens,
            "window_tokens": self.window_tokens,
            "fill_ratio": self.fill_ratio,
            "message_count": self.message_count,
            "categories": self.categories,
        }


def context_snapshot(
    messages: list[BaseMessage],
    system_text: str,
    *,
    window_tokens: int,
) -> ContextSnapshot:
    """Misura i token del contesto effettivo e come si distribuiscono per categoria.

    ``window_tokens`` è la finestra di riferimento mostrata in UI (``harness_context_window``):
    serve a dare un ``fill_ratio`` con cui colorare la barra. La compaction vera scatta invece
    sulla finestra reale del modello, che deepagents legge dal profilo del modello.
    """
    categories: dict[str, int] = {}
    total = 0
    if system_text:
        size = token_estimate(system_text)
        total += size
        categories["System & memoria"] = categories.get("System & memoria", 0) + size
    for message in messages:
        size = token_estimate(_content_text(message))
        if isinstance(message, AIMessage):
            for call in message.tool_calls:
                size += token_estimate(str(call.get("args", "")))
        total += size
        cat = _category(message)
        categories[cat] = categories.get(cat, 0) + size
    fill = round(total / window_tokens, 4) if window_tokens > 0 else 0.0
    return ContextSnapshot(
        total_tokens=total,
        window_tokens=window_tokens,
        fill_ratio=fill,
        message_count=len(messages),
        categories=categories,
    )


def detect_compaction(previous_peak: int, current_total: int, *, drop_ratio: float = 0.7) -> bool:
    """Vero se i token effettivi sono crollati sotto ``drop_ratio`` del picco precedente.

    Dentro un run i token del contesto salgono monotoni finché la compaction non li taglia di
    netto. Un calo marcato rispetto al picco è quindi la firma osservabile di una riduzione
    avvenuta, senza dover ispezionare lo stato privato del middleware di summarization.
    """
    if previous_peak <= 0:
        return False
    return current_total < previous_peak * drop_ratio


class ContextMonitorMiddleware(AgentMiddleware[Any, Any, Any]):
    """Emette snapshot del contesto e rileva le compaction, senza modificare la richiesta."""

    def __init__(
        self,
        *,
        window_tokens: int,
        event_callback: EventSink | None = None,
        warning_ratio: float = 0.7,
        compaction_ratio: float = 0.8,
        compaction_mode: Literal["automatic", "manual"] = "automatic",
    ) -> None:
        super().__init__()
        self._window = max(1, int(window_tokens))
        self._emit = event_callback
        self._warning_ratio = warning_ratio
        self._compaction_ratio = compaction_ratio
        self._compaction_mode = compaction_mode
        self._peak_tokens = 0
        self._last_pressure: str | None = None

    def _observe(self, request: ModelRequest) -> None:
        if self._emit is None:
            return
        system_text = ""
        system = getattr(request, "system_message", None)
        if system is not None:
            system_text = _content_text(system)
        snapshot = context_snapshot(
            list(request.messages), system_text, window_tokens=self._window
        )
        # Compaction: il contesto effettivo è crollato sotto una frazione del picco del run.
        if detect_compaction(self._peak_tokens, snapshot.total_tokens):
            self._emit(
                {
                    "type": "context.compaction.detected",
                    "tokens_before": self._peak_tokens,
                    "tokens_after": snapshot.total_tokens,
                    "tokens_reclaimed": self._peak_tokens - snapshot.total_tokens,
                    "window_tokens": self._window,
                    "mode": self._compaction_mode,
                }
            )
            self._peak_tokens = snapshot.total_tokens
        else:
            self._peak_tokens = max(self._peak_tokens, snapshot.total_tokens)
        if snapshot.fill_ratio >= self._compaction_ratio:
            pressure = "high"
        elif snapshot.fill_ratio >= self._warning_ratio:
            pressure = "warning"
        else:
            pressure = "ok"
        # Emette lo snapshot solo quando il livello di pressione cambia: senza questo, un
        # evento per ogni chiamata al modello riempirebbe il DB (come già successo con
        # usage.live). Ogni evento così è un fatto — «entrato in zona warning» — non rumore.
        if pressure != self._last_pressure:
            self._last_pressure = pressure
            event = snapshot.to_event()
            event["pressure"] = pressure
            self._emit(event)

    def wrap_model_call(
        self, request: ModelRequest, handler: Callable[[ModelRequest], ModelResponse]
    ) -> ModelResponse:
        self._observe(request)
        return handler(request)

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        self._observe(request)
        return await handler(request)


__all__ = [
    "ContextMonitorMiddleware",
    "ContextSnapshot",
    "context_snapshot",
    "detect_compaction",
]
