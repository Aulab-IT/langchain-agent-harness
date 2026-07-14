"""Instradamento su una scala di tre gradini di costo crescente.

Storia breve di questo file, perché spiega la forma che ha adesso.

Il primo router decideva sull'ultimo messaggio della lista, che durante un turno è quasi sempre
un `ToolMessage`: l'output di un tool contenente la parola "refactor" faceva scattare il modello
caro. E la soglia sulla lunghezza (`len(messages) > 24`) era a senso unico, perché il numero di
messaggi non diminuisce mai.

Il secondo leggeva l'ultimo messaggio **umano** e cercava parole chiave. Meglio, ma restava un
*predittore*: guardava la richiesta e scommetteva sulla difficoltà, prima che succedesse
qualcosa. Sbagliava in due modi — saliva su richieste banali che contenevano una parola cara, e
restava in basso su richieste difficili scritte in una lingua che le liste non coprivano.
Misurato: `analyze the csv file` restava in basso, `analizza il csv` saliva.

Questo non predice. **Parte dal gradino più basso e sale solo quando il gradino ha fallito.**
Il segnale non è una parola, è il grader: se la risposta non supera il criterio di uscita, la
continuazione riparte un gradino sopra. Non ci sono liste di parole, quindi non c'è nessuna
lingua privilegiata; e non si paga il modello caro per una richiesta che il modello economico
avrebbe risolto, perché prima gli si lascia provare.

Costa una iterazione in più sui compiti difficili. Costava cinque volte tanto su quelli facili
che contenevano la parola sbagliata.

La decisione resta congelata per tutto il turno aperto da un messaggio umano: dentro un turno
`messages[-1]` alterna fra `AIMessage` e `ToolMessage`, e ricalcolare a ogni chiamata farebbe
oscillare il modello a metà ragionamento.

L'utente può sempre scavalcare la scelta, per sessione o con un marcatore nel messaggio.
"""

from __future__ import annotations

import re
import time
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

from agent_harness.model_errors import invoke_with_model_retry, model_error_details
from agent_harness.run_budget import BudgetRate, RunBudgetTracker, estimate_request_tokens

Tier = Literal["low", "mid", "high"]
Override = Literal["auto", "low", "mid", "high"]

TIERS: tuple[Tier, ...] = ("low", "mid", "high")

# Etichette italiane usate in interfaccia e nel marcatore di messaggio.
TIER_LABELS: dict[Tier, str] = {"low": "basso", "mid": "medio", "high": "alto"}

# Marcatore che l'utente può scrivere a mano nel testo per forzare un gradino. È in chiaro:
# nulla entra nel prompt di nascosto. `base` e `forte` sopravvivono come alias della vecchia
# scala binaria — sono già dentro i messaggi salvati e nei checkpoint, e smettere di capirli
# non li toglierebbe da lì.
_MESSAGE_OVERRIDE = re.compile(
    r"\[modello:\s*(basso|medio|alto|low|mid|high|base|forte|default|strong)\]",
    re.IGNORECASE,
)
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


@dataclass(frozen=True)
class RouteDecision:
    tier: Tier
    reason: str
    source: Literal["message_override", "session_override", "escalation", "default"]


@dataclass(frozen=True)
class TierModel:
    """Un gradino: il modello, il suo reasoning effort, e l'istanza già costruita."""

    name: str
    effort: str
    model: BaseChatModel


class TierLadder:
    """Il gradino corrente del run, condiviso fra `GoalRunner` e il router.

    Muta in un punto solo — `escalate()`, chiamato dal runner quando l'iterazione non ha
    superato il criterio di uscita — e si azzera all'inizio di ogni obiettivo.
    """

    def __init__(self, start: Tier = "low") -> None:
        self._start: Tier = start
        self.current: Tier = start

    def reset(self) -> None:
        self.current = self._start

    def escalate(self) -> bool:
        """Sale di un gradino. False se era già in cima: non c'è dove salire."""
        index = TIERS.index(self.current)
        if index == len(TIERS) - 1:
            return False
        self.current = TIERS[index + 1]
        return True


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
    ladder: TierLadder,
    *,
    session_override: Override = "auto",
) -> RouteDecision:
    """Sceglie il gradino per il turno aperto dall'ultimo messaggio umano.

    Precedenza crescente di autorità: il gradino raggiunto per escalation è il default, la
    sessione lo scavalca, il marcatore nel messaggio scavalca tutto.
    """
    human = _last_human(messages)
    text = _text(human).casefold() if human is not None else ""

    match = _MESSAGE_OVERRIDE.search(text)
    if match:
        tier = _OVERRIDE_ALIASES[match.group(1).casefold()]
        return RouteDecision(tier, "richiesto in questo messaggio", "message_override")

    if session_override != "auto":
        return RouteDecision(session_override, "impostato per questa sessione", "session_override")

    if ladder.current != "low":
        return RouteDecision(
            ladder.current,
            "il gradino precedente non ha superato il criterio di uscita",
            "escalation",
        )

    return RouteDecision("low", "primo tentativo, gradino più economico", "default")


def build_model_router(
    tiers: dict[Tier, TierModel],
    ladder: TierLadder,
    *,
    session_override: Override = "auto",
    event_callback: Callable[[dict[str, Any]], None] | None = None,
    budget_tracker: RunBudgetTracker | None = None,
    budget_rates: dict[Tier, BudgetRate] | None = None,
) -> AgentMiddleware[Any, Any, Any]:
    """Instrada sulla scala e dichiara la scelta con un evento `model.selected`."""

    # La decisione si ricalcola solo quando cambia il messaggio umano in coda, o quando il
    # gradino è salito: dentro un turno resta congelata e l'evento non si ripete.
    state: dict[str, Any] = {"turn": None, "call": 0}

    @wrap_model_call
    async def route_model(
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        messages = request.messages
        human = _last_human(messages)
        turn_key = "" if human is None else human.id or _text(human)[:120]

        decision = decide_tier(messages, ladder, session_override=session_override)
        chosen = tiers[decision.tier]
        fingerprint = f"{turn_key}|{decision.tier}"

        if event_callback is not None and state["turn"] != fingerprint:
            state["turn"] = fingerprint
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

        state["call"] += 1
        call_id = f"model-{state['call']}"
        started = time.monotonic()
        reservation = None
        tracker = budget_tracker
        if tracker is not None and budget_rates is not None:
            reservation = tracker.before_model_call(
                kind=f"root:{decision.tier}",
                rate=budget_rates[decision.tier],
                estimated_input_tokens=estimate_request_tokens(request),
            )
        if event_callback is not None:
            event_callback(
                {
                    "type": "model.started",
                    "call_id": call_id,
                    "model": chosen.name,
                    "tier": decision.tier,
                }
            )
        try:
            response = await invoke_with_model_retry(
                lambda: handler(request.override(model=chosen.model)),
                event_callback=event_callback,
                call_kind=f"root:{decision.tier}",
                model=chosen.name,
                on_retry=(
                    (lambda _exc, _details: tracker.record_retry_estimate(reservation))
                    if reservation is not None and tracker is not None
                    else None
                ),
            )
        except Exception as exc:
            if reservation is not None and tracker is not None:
                tracker.cancel_model_call(reservation)
            if event_callback is not None:
                event_callback(
                    {
                        "type": "model.failed",
                        "call_id": call_id,
                        "model": chosen.name,
                        "elapsed_ms": round((time.monotonic() - started) * 1_000),
                        "error": str(exc)[:500],
                        "error_details": model_error_details(exc),
                    }
                )
            raise
        if reservation is not None and tracker is not None:
            tracker.complete_model_call(reservation, response.result)
        if event_callback is not None:
            event_callback(
                {
                    "type": "model.completed",
                    "call_id": call_id,
                    "model": chosen.name,
                    "elapsed_ms": round((time.monotonic() - started) * 1_000),
                }
            )
        return response

    return route_model
