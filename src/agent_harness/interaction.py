"""Primitiva generica: fermarsi e guidare l'utente a compiere un'azione sbloccante.

Provider-agnostica. L'agente la usa ogni volta che è bloccato su qualcosa che solo
l'umano può fare nel mondo reale: consenso OAuth nel browser, installare un'app
(Slack/Discord), incollare un codice o token una-tantum, caricare un file di credenziali,
inserire un 2FA. Il run si sospende (`interrupt()` di LangGraph) finché l'utente non
risponde; poi l'agente riprende autonomamente con la risposta ricevuta.
"""

from __future__ import annotations

from typing import Any, Literal

from langchain_core.tools import BaseTool, StructuredTool
from langgraph.types import interrupt
from pydantic import BaseModel, Field

ResponseKind = Literal["confirm", "value", "file"]


class UserActionInput(BaseModel):
    title: str = Field(
        min_length=1,
        max_length=200,
        description="Titolo breve dell'azione richiesta (es. 'Autorizza accesso Google').",
    )
    instructions: str = Field(
        min_length=1,
        max_length=6_000,
        description=(
            "Istruzioni passo-passo in markdown che guidano l'utente a completare l'azione. "
            "Sii specifico: cosa aprire, cosa cliccare, cosa incollare indietro."
        ),
    )
    response_kind: ResponseKind = Field(
        default="confirm",
        description=(
            "Cosa deve restituire l'utente: 'confirm' (ha svolto l'azione fuori banda), "
            "'value' (incolla un valore: codice OAuth, token, URL di redirect), "
            "'file' (carica un file nel workspace, es. credentials.json)."
        ),
    )
    url: str | None = Field(
        default=None,
        max_length=2_000,
        description="Link opzionale da aprire (es. URL di consenso OAuth).",
    )


def request_user_action(
    title: str,
    instructions: str,
    response_kind: ResponseKind = "confirm",
    url: str | None = None,
) -> str:
    """Sospende il run e chiede all'utente di completare un'azione sbloccante."""
    result: Any = interrupt(
        {
            "type": "user_action",
            "title": title[:200],
            "instructions": instructions[:6_000],
            "response_kind": response_kind,
            "url": url,
        }
    )
    if isinstance(result, dict):
        if result.get("cancelled"):
            return (
                "L'utente ha annullato l'azione richiesta: non procedere oltre "
                "su questo percorso."
            )
        value = result.get("response")
        if value:
            return f"L'utente ha completato l'azione. Valore fornito: {value}"
        return "L'utente ha confermato di aver completato l'azione richiesta."
    return str(result)


def user_action_tool() -> BaseTool:
    return StructuredTool.from_function(
        func=request_user_action,
        name="request_user_action",
        description=(
            "Fermati e chiedi all'utente di compiere un'azione che solo lui può fare "
            "(consenso OAuth nel browser, installare un'app, incollare un codice/token, "
            "caricare un file di credenziali, 2FA). Fornisci istruzioni chiare passo-passo. "
            "Il run resta sospeso finché l'utente non risponde, poi riprendi con la risposta. "
            "Usalo come ultimo miglio quando una connessione esterna richiede un passaggio "
            "manuale; il resto (chiamate di rete) gestiscilo da solo con docker_exec "
            "with_network=true."
        ),
        args_schema=UserActionInput,
    )
