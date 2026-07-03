from __future__ import annotations

import json
import threading
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from langchain.agents.middleware import AgentMiddleware, ToolCallRequest
from langchain_core.messages import ToolMessage
from langgraph.types import Command

_LOCK = threading.Lock()
EventCallback = Callable[[dict[str, Any]], None]


class AuditMiddleware(AgentMiddleware):
    """Registra metadati dei tool senza argomenti, output o segreti."""

    def __init__(self, path: Path, event_callback: EventCallback | None = None) -> None:
        self.path = path
        self.event_callback = event_callback

    def _emit(
        self,
        *,
        request: ToolCallRequest,
        status: str,
        elapsed_ms: int | None = None,
    ) -> None:
        if self.event_callback is None:
            return
        payload: dict[str, Any] = {
            "type": f"tool.{status}",
            "tool": request.tool_call["name"],
        }
        if elapsed_ms is not None:
            payload["elapsed_ms"] = elapsed_ms
        args = request.tool_call.get("args", {})
        path = args.get("file_path") or args.get("path") if isinstance(args, dict) else None
        if isinstance(path, str) and path.startswith("/skills/"):
            parts = path.split("/")
            if len(parts) > 2 and parts[2]:
                payload["skill"] = parts[2]
        self.event_callback(payload)

    def _write(self, *, tool: str, status: str, elapsed_ms: int) -> None:
        event = {
            "timestamp": datetime.now(UTC).isoformat(),
            "tool": tool,
            "status": status,
            "elapsed_ms": elapsed_ms,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with _LOCK, self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False) + "\n")

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command[Any]],
    ) -> ToolMessage | Command[Any]:
        started = time.monotonic()
        tool_name = request.tool_call["name"]
        self._emit(request=request, status="started")
        try:
            result = handler(request)
        except Exception:
            elapsed = _elapsed(started)
            self._write(tool=tool_name, status="error", elapsed_ms=elapsed)
            self._emit(request=request, status="failed", elapsed_ms=elapsed)
            raise
        elapsed = _elapsed(started)
        self._write(tool=tool_name, status="ok", elapsed_ms=elapsed)
        self._emit(request=request, status="completed", elapsed_ms=elapsed)
        return result

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        started = time.monotonic()
        tool_name = request.tool_call["name"]
        self._emit(request=request, status="started")
        try:
            result = await handler(request)
        except Exception:
            elapsed = _elapsed(started)
            self._write(tool=tool_name, status="error", elapsed_ms=elapsed)
            self._emit(request=request, status="failed", elapsed_ms=elapsed)
            raise
        elapsed = _elapsed(started)
        self._write(tool=tool_name, status="ok", elapsed_ms=elapsed)
        self._emit(request=request, status="completed", elapsed_ms=elapsed)
        return result


def _elapsed(started: float) -> int:
    return round((time.monotonic() - started) * 1_000)
