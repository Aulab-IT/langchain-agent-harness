"""Instradamento su una scala di tre gradini di costo crescente.

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

La scala ha tre gradini, e la regola di costo è una sola: **si sta in basso finché qualcosa non
dice di salire.** Non esistono parole chiave per il gradino basso, perché è il luogo di riposo.
Un segnale debole (conversazione lunga) fa salire di un gradino, non di due.

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

Tier = Literal["low", "mid", "high"]
Override = Literal["auto", "low", "mid", "high"]

TIERS: tuple[Tier, ...] = ("low", "mid", "high")

# Etichette italiane usate in interfaccia e nel marcatore di messaggio.
TIER_LABELS: dict[Tier, str] = {"low": "basso", "mid": "medio", "high": "alto"}

# Marcatore che il composer aggiunge al messaggio quando l'utente forza un gradino. È in
# chiaro nel testo: l'utente vede esattamente cosa ha chiesto, nulla entra nel prompt di
# nascosto. Vedi `client/src/lib/modelOverride.ts`.
_MESSAGE_OVERRIDE = re.compile(
    r"\[modello:\s*(basso|medio|alto|low|mid|high|base|forte|default|strong)\]",
    re.IGNORECASE,
)
# `base` e `forte` sopravvivono come alias della vecchia scala binaria: sono già scritti nei
# messaggi salvati e nei checkpoint, e riscriverli sarebbe riscrivere la storia della chat.
_OVERRIDE_ALIASES: dict[str, Tier] = {
    "basso": "low",
    "low": "low",
    "base": "low",
    "default": "low",
    "medio": "mid",
    "mid": "mid",
    "alto": "high",
    "high": "high",
    "forte": "high",
    "strong": "high",
}

# Il gradino alto costa cinque volte il basso in input e cinque in output. Ci si sale solo se la
# richiesta *dichiara* complessità strutturale. Parole troppo comuni ("design", "prove", "test")
# sono escluse di proposito: una falsa corrispondenza qui è la voce di spesa più cara del sistema.
DEFAULT_HIGH_KEYWORDS = (
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

# Il gradino medio costa due volte e mezza il basso. Ci si sale per lavoro nell'ambiente o su più
# fonti: cose che il gradino basso sbaglia abbastanza spesso da rendere il risparmio illusorio,
# perché una risposta sbagliata si paga con un'altra iterazione.
DEFAULT_MID_KEYWORDS = (
    "confronta",
    "verifica",
    "debug",
    "analizza",
    "riscrivi",
    "ottimizza",
    "spiega perché",
    "compare",
    "investigate",
    "optimi",
    "explain why",
)


@dataclass(frozen=True)
class RouteDecision:
    tier: Tier
    reason: str
    source: Literal["message_override", "session_override", "keyword", "context_size", "default"]


@dataclass(frozen=True)
class TierModel:
    """Un gradino: il modello, il suo reasoning effort, e l'istanza già costruita."""

    name: str
    effort: str
    model: BaseChatModel


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


def decide_tier(
    messages: Sequence[BaseMessage],
    *,
    session_override: Override = "auto",
    high_keywords: tuple[str, ...] = DEFAULT_HIGH_KEYWORDS,
    mid_keywords: tuple[str, ...] = DEFAULT_MID_KEYWORDS,
    context_threshold: int = 40,
) -> RouteDecision:
    """Sceglie il gradino per il turno aperto dall'ultimo messaggio umano.

    L'ordine è di precedenza crescente di autorità: il contesto è il segnale più debole, la
    richiesta esplicita dell'utente sul singolo messaggio è la più forte. A parità di segnali
    si sceglie il gradino più basso.
    """
    human = _last_human(messages)
    text = _text(human).casefold() if human is not None else ""

    match = _MESSAGE_OVERRIDE.search(text)
    if match:
        tier = _OVERRIDE_ALIASES[match.group(1).casefold()]
        return RouteDecision(tier, "richiesto in questo messaggio", "message_override")

    if session_override != "auto":
        return RouteDecision(session_override, "impostato per questa sessione", "session_override")

    matched = next((word for word in high_keywords if word in text), None)
    if matched:
        return RouteDecision("high", f"la richiesta contiene «{matched}»", "keyword")

    matched = next((word for word in mid_keywords if word in text), None)
    if matched:
        return RouteDecision("mid", f"la richiesta contiene «{matched}»", "keyword")

    if len(messages) > context_threshold:
        # Un solo gradino: la lunghezza è un indizio debole, e il salto al gradino alto
        # quintuplicherebbe il costo di ogni turno successivo per un sospetto.
        return RouteDecision(
            "mid", f"conversazione lunga ({len(messages)} messaggi)", "context_size"
        )

    return RouteDecision("low", "richiesta ordinaria", "default")


def build_model_router(
    tiers: dict[Tier, TierModel],
    *,
    session_override: Override = "auto",
    high_keywords: tuple[str, ...] = DEFAULT_HIGH_KEYWORDS,
    mid_keywords: tuple[str, ...] = DEFAULT_MID_KEYWORDS,
    context_threshold: int = 40,
    event_callback: Callable[[dict[str, Any]], None] | None = None,
) -> AgentMiddleware[Any, Any, Any]:
    """Instrada sulla scala e dichiara la scelta con un evento `model.selected`."""

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

        decision = decide_tier(
            messages,
            session_override=session_override,
            high_keywords=high_keywords,
            mid_keywords=mid_keywords,
            context_threshold=context_threshold,
        )
        chosen = tiers[decision.tier]

        if event_callback is not None and state["turn"] != turn_key:
            state["turn"] = turn_key
            event_callback(
                {
                    "type": "model.selected",
                    "model": chosen.name,
                    "tier": decision.tier,
                    "effort": chosen.effort,
                    "reason": decision.reason,
                    "source": decision.source,
                }
            )

        return await handler(request.override(model=chosen.model))

    return route_model
