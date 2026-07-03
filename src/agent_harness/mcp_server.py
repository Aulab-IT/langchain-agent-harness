from __future__ import annotations

import re

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("harness-didattico")


@mcp.tool()
def count_text(text: str) -> dict[str, int]:
    """Conta caratteri, parole e righe senza inviare il testo a servizi esterni."""
    return {
        "characters": len(text),
        "words": len(re.findall(r"\S+", text)),
        "lines": len(text.splitlines()),
    }


@mcp.tool()
def harness_glossary(term: str) -> str:
    """Restituisce una breve definizione locale di un termine dell'agent harness."""
    entries = {
        "harness": "Codice, configurazione ed esecuzione che trasformano un modello in agente.",
        "react": "Ciclo nel quale il modello ragiona, agisce con un tool e osserva il risultato.",
        "compaction": "Sintesi selettiva del contesto per proseguire senza superare la finestra.",
        "skill": "Procedura caricata su richiesta mediante progressive disclosure.",
        "checkpoint": "Snapshot dello stato LangGraph associato a un thread.",
    }
    return entries.get(term.casefold(), "Termine non presente nel glossario locale.")


if __name__ == "__main__":
    mcp.run(transport="stdio")

