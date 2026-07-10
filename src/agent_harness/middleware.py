"""Instradamento fra modello di default e modello forte.

Il router precedente decideva sull'ultimo messaggio della lista, che durante un turno è quasi
sempre un `ToolMessage`: l'output di un tool contenente la parola "refactor" faceva scattare il
modello forte. E la soglia sulla lunghezza (`len(messages) > 24`) era a senso unico, perché il
numero di messaggi non diminuisce mai: superata una volta, il modello forte restava scelto per
sempre. Nessuna isteresi può rimediare a una grandezza monotona.

Qui la decisione si prende sull'ultimo messaggio **umano** — l'unica cosa che esprima davvero
l'intento — e resta stabile per tutto il turno che quel messaggio ha aperto. È questa la
stabilità che serve: dentro un turno `messages[-1]` continua a cambiare fra `AIMessage` e
`ToolMessage`, e una decisione ricalcolata a ogni giro farebbe oscillare il modello a metà
ragionamento.

L'utente può sempre scavalcare la scelta, per sessione o per singolo messaggio.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from langchain.agents.middleware import (
    AgentMiddleware,
    ModelRequest,
    ModelResponse,
    wrap_model_call,
)
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage

ModelChoice = Literal["default", "strong"]
Override = Literal["auto", "default", "strong"]

# Marcatore che il composer aggiunge al messaggio quando l'utente forza un modello. È in
# chiaro nel testo: l'utente vede esattamente cosa ha chiesto, nulla entra nel prompt di
# nascosto. Vedi `client/src/lib/modelOverride.ts`.
_MESSAGE_OVERRIDE = re.compile(r"\[modello:\s*(forte|base|strong|default)\]", re.IGNORECASE)
_OVERRIDE_ALIASES: dict[str, ModelChoice] = {
    "forte": "strong",
    "strong": "strong",
    "base": "default",
    "default": "default",
}

# Bilingue perché l'harness parla italiano ma i prompt tecnici arrivano spesso in inglese.
# Ogni parola qui dentro costa: una falsa corrispondenza manda al modello forte una richiesta
# banale. Sono escluse di proposito parole troppo comuni ("design", "prove", "test").
DEFAULT_STRONG_KEYWORDS = (
    "complesso",
    "complessa",
    "architettura",
    "approfondito",
    "approfondita",
    "refactor",
    "multi-file",
    "dimostra",
    "complex",
    "architecture",
    "in depth",
    "thorough",
)


@dataclass(frozen=True)
class RouteDecision:
    choice: ModelChoice
    reason: str
    source: Literal["message_override", "session_override", "keyword", "context_size", "default"]


def _last_human(messages: Sequence[BaseMessage]) -> BaseMessage | None:
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            return message
    return None


def _text(message: BaseMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    # Contenuto multimodale: concateniamo solo le parti testuali.
    parts = [
        str(block.get("text", ""))
        for block in content
        if isinstance(block, dict) and block.get("type") == "text"
    ]
    return " ".join(parts)


def decide_model(
    messages: Sequence[BaseMessage],
    *,
    session_override: Override = "auto",
    strong_keywords: tuple[str, ...] = DEFAULT_STRONG_KEYWORDS,
    context_threshold: int = 40,
) -> RouteDecision:
    """Sceglie il modello per il turno aperto dall'ultimo messaggio umano.

    L'ordine è di precedenza crescente di autorità: il contesto è il segnale più debole, la
    richiesta esplicita dell'utente sul singolo messaggio è la più forte.
    """
    human = _last_human(messages)
    text = _text(human).casefold() if human is not None else ""

    match = _MESSAGE_OVERRIDE.search(text)
    if match:
        choice = _OVERRIDE_ALIASES[match.group(1).casefold()]
        return RouteDecision(choice, "richiesto in questo messaggio", "message_override")

    if session_override in ("default", "strong"):
        return RouteDecision(session_override, "impostato per questa sessione", "session_override")

    matched = next((word for word in strong_keywords if word in text), None)
    if matched:
        return RouteDecision("strong", f"la richiesta contiene «{matched}»", "keyword")

    if len(messages) > context_threshold:
        return RouteDecision(
            "strong",
            f"conversazione lunga ({len(messages)} messaggi)",
            "context_size",
        )

    return RouteDecision("default", "richiesta ordinaria", "default")


def build_model_router(
    default_model: BaseChatModel,
    strong_model: BaseChatModel,
    *,
    default_name: str = "",
    strong_name: str = "",
    session_override: Override = "auto",
    strong_keywords: tuple[str, ...] = DEFAULT_STRONG_KEYWORDS,
    context_threshold: int = 40,
    event_callback: Callable[[dict[str, Any]], None] | None = None,
) -> AgentMiddleware[Any, Any, Any]:
    """Instrada verso il modello forte e dichiara la scelta con un evento `model.selected`."""

    # La decisione si ricalcola solo quando cambia il messaggio umano in coda: dentro un turno
    # resta congelata, e l'evento non si ripete a ogni chiamata al modello.
    state: dict[str, str | None] = {"turn": None}

    @wrap_model_call
    async def route_model(
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        messages = request.messages
        human = _last_human(messages)
        turn_key = "" if human is None else human.id or _text(human)[:120]

        decision = decide_model(
            messages,
            session_override=session_override,
            strong_keywords=strong_keywords,
            context_threshold=context_threshold,
        )
        selected = strong_model if decision.choice == "strong" else default_model
        name = (strong_name if decision.choice == "strong" else default_name) or decision.choice

        if event_callback is not None and state["turn"] != turn_key:
            state["turn"] = turn_key
            event_callback(
                {
                    "type": "model.selected",
                    "model": name,
                    "choice": decision.choice,
                    "reason": decision.reason,
                    "source": decision.source,
                }
            )

        return await handler(request.override(model=selected))

    return route_model
