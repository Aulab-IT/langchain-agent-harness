"""Guardia sui blocchi-file inviati al modello: scarta i binari malformati prima del provider.

Quando l'agente legge un file binario, deepagents lo allega alla conversazione come blocco
multimodale ``{"type": "file"|"image", "base64": ..., "mime_type": ...}`` così il modello può
"vederlo". Ma se quel file non è valido — un PDF finto di pochi byte scritto per errore da un
modello debole — il provider rifiuta l'INTERA richiesta con un 400 (``invalid_file``). E poiché
il blocco resta nella storia del thread, ogni chiamata successiva lo rimanda: la conversazione
diventa irrecuperabile, ogni «riprova» muore sul nascere.

Questa guardia ispeziona i blocchi in uscita a ogni chiamata al modello e sostituisce quelli
palesemente corrotti con una nota testuale. Il modello vede «file non valido, rimosso» invece
di un blocco che avvelena la richiesta, e il run può proseguire. È logica pura sui messaggi,
testabile offline: valida la firma dei formati che sa controllare (oggi il PDF), lascia passare
il resto invariato.
"""

from __future__ import annotations

import base64
from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware import (
    AgentMiddleware,
    ModelRequest,
    ModelResponse,
)
from langchain_core.messages import BaseMessage

# Byte iniziali attesi per i formati che sappiamo validare. Un file che dichiara questo
# mime ma non inizia con la firma è corrotto e non va mandato al provider.
_MAGIC: dict[str, bytes] = {
    "application/pdf": b"%PDF",
}

_REMOVED_NOTE = "[file non valido rimosso: il contenuto non corrisponde al tipo dichiarato]"


def _is_corrupt_file_block(block: Any) -> bool:
    """Vero se il blocco dichiara un formato noto ma il suo contenuto non ne ha la firma."""
    if not isinstance(block, dict):
        return False
    mime = block.get("mime_type")
    data = block.get("base64")
    magic = _MAGIC.get(str(mime))
    if magic is None or not isinstance(data, str):
        return False
    try:
        head = base64.b64decode(data, validate=False)[: len(magic)]
    except Exception:
        # base64 illeggibile: è comunque un blocco che il provider rifiuterebbe.
        return True
    return head != magic


def sanitize_messages(messages: list[BaseMessage]) -> tuple[list[BaseMessage], int]:
    """Sostituisce i blocchi-file corrotti con una nota testuale. Ritorna (messaggi, quanti puliti).

    Tocca solo i messaggi con almeno un blocco corrotto: gli altri passano per riferimento, così
    non si ricostruisce inutilmente l'intera lista a ogni chiamata.
    """
    cleaned = 0
    result: list[BaseMessage] = []
    for message in messages:
        content = message.content
        if not isinstance(content, list) or not any(
            _is_corrupt_file_block(block) for block in content
        ):
            result.append(message)
            continue
        new_content: list[Any] = []
        for block in content:
            if _is_corrupt_file_block(block):
                cleaned += 1
                new_content.append({"type": "text", "text": _REMOVED_NOTE})
            else:
                new_content.append(block)
        result.append(message.model_copy(update={"content": new_content}))
    return result, cleaned


class FileBlockGuardMiddleware(AgentMiddleware[Any, Any, Any]):
    """Rimuove dalla richiesta i blocchi-file corrotti, prima che raggiungano il provider."""

    def wrap_model_call(
        self, request: ModelRequest, handler: Callable[[ModelRequest], ModelResponse]
    ) -> ModelResponse:
        sanitized, cleaned = sanitize_messages(list(request.messages))
        if cleaned:
            request = request.override(messages=sanitized)
        return handler(request)

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        sanitized, cleaned = sanitize_messages(list(request.messages))
        if cleaned:
            request = request.override(messages=sanitized)
        return await handler(request)


__all__ = ["FileBlockGuardMiddleware", "sanitize_messages"]
