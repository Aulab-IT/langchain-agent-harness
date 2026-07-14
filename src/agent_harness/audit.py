from __future__ import annotations

import json
import re
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
from agent_harness.run_budget import SubagentProgressState

_LOCK = threading.Lock()
EventCallback = Callable[[dict[str, Any]], None]
_SUBAGENT_SCOPE: ContextVar[dict[str, Any] | None] = ContextVar("subagent_scope", default=None)
_NONZERO_EXIT = re.compile(r"\bexit_code\s*=\s*([1-9]\d*)\b", re.IGNORECASE)
_SPACE = re.compile(r"\s+")
_FATAL_ENVIRONMENT_MARKERS = (
    "could not open lock file /var/lib/apt",
    "are you root?",
    "sudo: command not found",
    "operation not permitted",
)
_DEPENDENCY_MISSING_MARKERS = (
    "modulenotfounderror",
    "no module named",
    "package(s) not found",
    "command not found",
    "cannot import name",
)


class SubagentExecutionBlocked(RuntimeError):
    """Errore operativo non recuperabile senza cambiare ambiente o intervento umano."""

    blocked = True


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
        task_observer: Callable[[str, str], None] | None = None,
        task_coordinator: Any = None,
        tool_observer: Callable[[dict[str, Any]], None] | None = None,
        progress_state: SubagentProgressState | None = None,
    ) -> None:
        self.path = path
        self.event_callback = event_callback
        self.run_id = run_id
        self.session_id = session_id
        self.subagent_name = subagent_name
        self.task_semaphore = task_semaphore
        self.task_observer = task_observer
        self.task_coordinator = task_coordinator
        self.tool_observer = tool_observer
        self.progress_state = progress_state
        self._paused_calls: set[str] = set()
        self._paused_lock = threading.Lock()
        self._tool_failure_counts: dict[str, int] = {}

    @staticmethod
    def _tool_outcomes(result: Any) -> list[str]:
        text = str(_result_content(result))
        lowered = text.lower()
        compact = _SPACE.sub(" ", lowered)
        outcomes: list[str] = []
        if "pass-with-warnings" in lowered and any(
            marker in compact for marker in ('"errors": []', "'errors': []", "errors: []")
        ):
            outcomes.append("validation_passed_with_warnings")
        if any(marker in lowered for marker in _DEPENDENCY_MISSING_MARKERS):
            outcomes.append("dependency_missing")
        return outcomes

    def _annotate_subagent_result(self, request: ToolCallRequest, result: Any) -> Any:
        if not self.subagent_name:
            return result
        outcomes = self._tool_outcomes(result)
        if not outcomes:
            return result
        if self.progress_state is not None:
            self.progress_state.record(outcomes)
        if self.event_callback is not None:
            self.event_callback(
                {
                    "type": "subagent.tool.outcome",
                    "subagent": self.subagent_name,
                    "tool": str(request.tool_call.get("name", "tool")),
                    "tool_call_id": str(request.tool_call.get("id", "")),
                    "outcomes": outcomes,
                }
            )
        notes = ["[HARNESS TOOL OUTCOME]"]
        if "validation_passed_with_warnings" in outcomes:
            notes.append(
                "Validation passed with warnings and zero errors. Count it as successful unless "
                "a warning violates an explicit success criterion."
            )
        if "dependency_missing" in outcomes:
            notes.append(
                "Dependency missing. Do not repeat environment probes. Optional or duplicate "
                "validation may be reported as a limitation; mandatory dependency needs one "
                "approved install attempt or BLOCKED status."
            )
        note = "\n".join(notes)
        if isinstance(result, ToolMessage):
            content = result.content
            if isinstance(content, str):
                return result.model_copy(update={"content": f"{content}\n\n{note}"})
        if isinstance(result, str):
            return f"{result}\n\n{note}"
        return result

    def _guard_subagent_result(self, request: ToolCallRequest, result: Any) -> None:
        """Ferma retry subagent senza prospettiva: ambiente fatale o stesso errore due volte."""
        if not self.subagent_name:
            return
        text = str(_result_content(result))
        lowered = text.lower()
        nonzero = _NONZERO_EXIT.search(lowered)
        if not nonzero:
            return
        tool = str(request.tool_call.get("name", "tool"))
        fatal = next((marker for marker in _FATAL_ENVIRONMENT_MARKERS if marker in lowered), None)
        normalized = _SPACE.sub(" ", lowered)[-600:]
        signature = f"{tool}:{normalized}"
        count = self._tool_failure_counts.get(signature, 0) + 1
        self._tool_failure_counts[signature] = count
        if fatal is None and count < 2:
            return
        reason = (
            f"Ambiente bloccante per {tool}: {fatal}."
            if fatal
            else f"Retry fermato: {tool} ha restituito due volte lo stesso errore."
        )
        if self.event_callback is not None:
            self.event_callback(
                {
                    "type": "subagent.retry_stopped",
                    "subagent": self.subagent_name,
                    "tool": tool,
                    "reason": reason,
                    "attempts": count,
                }
            )
        raise SubagentExecutionBlocked(reason)

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
        if self.event_callback is None and self.tool_observer is None:
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
        tool_metadata = getattr(getattr(request, "tool", None), "metadata", None)
        if isinstance(tool_metadata, dict):
            for source, target in (
                ("tool_identity", "tool_identity"),
                ("tool_origin", "tool_origin"),
                ("tool_original_name", "tool_display_name"),
                ("mcp_server", "mcp_server"),
            ):
                value = tool_metadata.get(source)
                if isinstance(value, str) and value:
                    payload[target] = value
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
        if self.tool_observer is not None:
            self.tool_observer(dict(payload))
        if self.event_callback is not None:
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
            self.task_observer(scope["subagent"], call_id)
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
            result = self._annotate_subagent_result(request, result)
            self._guard_subagent_result(request, result)
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
        return cast(ToolMessage | Command[Any], result)

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
            if tool_name == "task" and isinstance(args, dict) and self.task_coordinator is not None:
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
            result = self._annotate_subagent_result(prepared_request, result)
            self._guard_subagent_result(prepared_request, result)
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
        return cast(ToolMessage | Command[Any], result)


def _elapsed(started: float) -> int:
    return round((time.monotonic() - started) * 1_000)
