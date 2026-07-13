from __future__ import annotations

import json
import threading
import time
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from langchain.agents.middleware import AgentMiddleware, ToolCallRequest
from langchain_core.messages import ToolMessage
from langgraph.errors import GraphInterrupt
from langgraph.types import Command

from agent_harness.config import SANDBOX_SKILLS_MOUNT

_LOCK = threading.Lock()
EventCallback = Callable[[dict[str, Any]], None]
_SUBAGENT_SCOPE: ContextVar[dict[str, Any] | None] = ContextVar("subagent_scope", default=None)


def _preview(value: Any, limit: int) -> str:
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=False)
        except (TypeError, ValueError):
            text = str(value)
    return text if len(text) <= limit else text[:limit] + "… (troncato)"


def _result_content(result: Any) -> Any:
    """Estrae il risultato finale del task invece del repr di `Command`."""
    if isinstance(result, Command) and isinstance(result.update, dict):
        messages = result.update.get("messages")
        if isinstance(messages, list) and messages:
            return getattr(messages[-1], "content", result)
    return getattr(result, "content", result)


class AuditMiddleware(AgentMiddleware):
    """Traccia i tool. Il file JSONL resta minimale; gli eventi per la trace UI
    includono argomenti e output (troncati) per un'ispezione tipo LangSmith."""

    def __init__(
        self,
        path: Path,
        event_callback: EventCallback | None = None,
        *,
        run_id: str | None = None,
        session_id: str | None = None,
        subagent_name: str | None = None,
        task_semaphore: Any = None,
        task_observer: Callable[[str], None] | None = None,
        task_coordinator: Any = None,
    ) -> None:
        self.path = path
        self.event_callback = event_callback
        self.run_id = run_id
        self.session_id = session_id
        self.subagent_name = subagent_name
        self.task_semaphore = task_semaphore
        self.task_observer = task_observer
        self.task_coordinator = task_coordinator
        self._paused_calls: set[str] = set()
        self._paused_lock = threading.Lock()

    def _opening_status(self, request: ToolCallRequest, execution: Any = None) -> str:
        call_id = str(request.tool_call.get("id", ""))
        with self._paused_lock:
            resumed = call_id in self._paused_calls
            self._paused_calls.discard(call_id)
        if execution is not None and getattr(execution, "resumed", False):
            resumed = True
            execution.resumed = False
        return "resumed" if resumed else "started"

    def _mark_paused(self, request: ToolCallRequest) -> None:
        call_id = str(request.tool_call.get("id", ""))
        if call_id:
            with self._paused_lock:
                self._paused_calls.add(call_id)

    def _emit(
        self,
        *,
        request: ToolCallRequest,
        status: str,
        elapsed_ms: int | None = None,
        result: Any = None,
        execution: Any = None,
    ) -> None:
        if self.event_callback is None:
            return
        args = request.tool_call.get("args", {})
        tool_name = request.tool_call["name"]
        call_id = str(request.tool_call.get("id", ""))
        scope = _SUBAGENT_SCOPE.get()
        if tool_name == "task" and isinstance(args, dict):
            event_type = f"subagent.{status}"
        elif scope is not None and self.subagent_name:
            event_type = f"subagent.tool.{status}"
        else:
            event_type = f"tool.{status}"
        payload: dict[str, Any] = {
            "type": event_type,
            "tool": request.tool_call["name"],
            "tool_call_id": call_id,
        }
        if tool_name == "task" and isinstance(args, dict):
            payload.update(
                {
                    "invocation_id": call_id,
                    "subagent": str(args.get("subagent_type", "")),
                    "description": str(args.get("description", ""))[:1_500],
                }
            )
            if execution is not None:
                payload.update(
                    {
                        "routing_task_id": execution.task.id,
                        "depends_on": execution.task.depends_on,
                        "attempt": execution.attempt,
                        "status": execution.status,
                        "objective_met": execution.objective_met,
                        "input_artifacts": execution.input_artifacts,
                        "output_artifacts": execution.output_artifacts,
                    }
                )
        elif scope is not None and self.subagent_name:
            payload.update({**scope, "subagent": self.subagent_name})
        if elapsed_ms is not None:
            payload["elapsed_ms"] = elapsed_ms
        if status == "started" and args:
            payload["args"] = _preview(args, 1_500)
        if status in {"completed", "failed"} and result is not None:
            payload["output"] = _preview(_result_content(result), 4_000)
        path = args.get("file_path") or args.get("path") if isinstance(args, dict) else None
        if isinstance(path, str) and path.startswith(f"{SANDBOX_SKILLS_MOUNT}/"):
            parts = path.split("/")
            if len(parts) > 2 and parts[2]:
                payload["skill"] = parts[2]
        self.event_callback(payload)

    def _task_scope(
        self, request: ToolCallRequest, execution: Any = None
    ) -> tuple[Any, dict[str, Any] | None]:
        args = request.tool_call.get("args", {})
        if request.tool_call["name"] != "task" or not isinstance(args, dict):
            return None, None
        call_id = str(request.tool_call.get("id", ""))
        scope = {
            "invocation_id": call_id,
            "parent_tool_call_id": call_id,
            "subagent": str(args.get("subagent_type", "")),
        }
        if execution is not None:
            scope.update(
                {
                    "routing_task_id": execution.task.id,
                    "depends_on": execution.task.depends_on,
                    "attempt": execution.attempt,
                }
            )
        if self.task_observer is not None:
            self.task_observer(scope["subagent"])
        return _SUBAGENT_SCOPE.set(scope), scope

    def _write(self, *, tool: str, status: str, elapsed_ms: int) -> None:
        event = {
            "timestamp": datetime.now(UTC).isoformat(),
            "tool": tool,
            "status": status,
            "elapsed_ms": elapsed_ms,
        }
        if self.run_id:
            event["run_id"] = self.run_id
        if self.session_id:
            event["session_id"] = self.session_id
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
        token, _ = self._task_scope(request)
        self._emit(request=request, status=self._opening_status(request))
        try:
            result = handler(request)
        except GraphInterrupt:
            elapsed = _elapsed(started)
            self._mark_paused(request)
            self._write(tool=tool_name, status="paused", elapsed_ms=elapsed)
            self._emit(request=request, status="paused", elapsed_ms=elapsed)
            raise
        except Exception:
            elapsed = _elapsed(started)
            self._write(tool=tool_name, status="error", elapsed_ms=elapsed)
            self._emit(request=request, status="failed", elapsed_ms=elapsed)
            raise
        finally:
            if token is not None:
                _SUBAGENT_SCOPE.reset(token)
        elapsed = _elapsed(started)
        self._write(tool=tool_name, status="ok", elapsed_ms=elapsed)
        self._emit(request=request, status="completed", elapsed_ms=elapsed, result=result)
        return result

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        started = time.monotonic()
        tool_name = request.tool_call["name"]
        prepared_request = request
        execution = None
        token = None
        try:
            args = request.tool_call.get("args", {})
            if (
                tool_name == "task"
                and isinstance(args, dict)
                and self.task_coordinator is not None
            ):
                execution, prepared_description = await self.task_coordinator.prepare_delegation(
                    str(args.get("subagent_type", "")),
                    str(args.get("description", "")),
                    str(request.tool_call.get("id", "")),
                )
                if prepared_description != args.get("description"):
                    prepared_call = {
                        **request.tool_call,
                        "args": {**args, "description": prepared_description},
                    }
                    prepared_request = request.override(tool_call=cast(Any, prepared_call))
            token, _ = self._task_scope(prepared_request, execution)
            self._emit(
                request=prepared_request,
                status=self._opening_status(prepared_request, execution),
                execution=execution,
            )
            if tool_name == "task" and self.task_semaphore is not None:
                async with self.task_semaphore:
                    result = await handler(prepared_request)
            else:
                result = await handler(prepared_request)
        except GraphInterrupt:
            elapsed = _elapsed(started)
            self._mark_paused(prepared_request)
            self._write(tool=tool_name, status="paused", elapsed_ms=elapsed)
            if self.task_coordinator is not None:
                self.task_coordinator.pause_delegation(execution)
            self._emit(
                request=prepared_request,
                status="paused",
                elapsed_ms=elapsed,
                execution=execution,
            )
            raise
        except Exception as exc:
            elapsed = _elapsed(started)
            self._write(tool=tool_name, status="error", elapsed_ms=elapsed)
            if self.task_coordinator is not None:
                self.task_coordinator.complete_delegation(execution, error=exc)
            self._emit(
                request=prepared_request,
                status="failed",
                elapsed_ms=elapsed,
                execution=execution,
            )
            raise
        finally:
            if token is not None:
                _SUBAGENT_SCOPE.reset(token)
        elapsed = _elapsed(started)
        self._write(tool=tool_name, status="ok", elapsed_ms=elapsed)
        if self.task_coordinator is not None:
            self.task_coordinator.complete_delegation(execution, result=result)
        self._emit(
            request=prepared_request,
            status="completed",
            elapsed_ms=elapsed,
            result=result,
            execution=execution,
        )
        return result


def _elapsed(started: float) -> int:
    return round((time.monotonic() - started) * 1_000)
