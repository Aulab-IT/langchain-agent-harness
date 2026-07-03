from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware import (
    AgentMiddleware,
    ModelRequest,
    ModelResponse,
    wrap_model_call,
)
from langchain_core.language_models.chat_models import BaseChatModel


def build_model_router(
    default_model: BaseChatModel,
    strong_model: BaseChatModel,
) -> AgentMiddleware[Any, Any, Any]:
    """Sceglie un modello forte quando contesto o richiesta indicano maggiore complessità."""

    @wrap_model_call
    async def route_model(
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        messages = request.messages
        last_text = str(messages[-1].content).casefold() if messages else ""
        complex_hint = any(
            word in last_text
            for word in ("complesso", "architettura", "approfondito", "refactor", "multi-file")
        )
        selected = strong_model if len(messages) > 24 or complex_hint else default_model
        return await handler(request.override(model=selected))

    return route_model
