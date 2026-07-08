from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, cast

from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

from agent_harness.factory import Harness
from agent_harness.prompts import CONTINUATION_PROMPT, VERIFICATION_FEEDBACK_PROMPT
from agent_harness.usage import compute_usage
from agent_harness.verification import GradeResult

ApprovalCallback = Callable[[dict[str, Any]], Awaitable[bool]]
RunEventCallback = Callable[[dict[str, Any]], None]


@dataclass
class RunResult:
    text: str
    iterations: int
    completed: bool
    messages: list[BaseMessage]


def final_text(messages: list[BaseMessage]) -> str:
    for message in reversed(messages):
        if isinstance(message, AIMessage):
            return message.text
    return ""


def requires_environment_verification(goal: str) -> bool:
    normalized = goal.casefold()
    return any(
        verb in normalized
        for verb in (
            "crea",
            "scrivi",
            "modifica",
            "implementa",
            "correggi",
            "aggiorna",
            "genera",
        )
    )


def has_successful_verification(messages: list[BaseMessage]) -> bool:
    return any(
        isinstance(message, ToolMessage)
        and message.name == "docker_exec"
        and "exit_code=0" in str(message.content)
        for message in messages
    )


class GoalRunner:
    """Aggiunge approvazione e continuazione limitata al graph dell'agente."""

    def __init__(
        self,
        harness: Harness,
        approval_callback: ApprovalCallback | None = None,
        event_callback: RunEventCallback | None = None,
    ) -> None:
        self.harness = harness
        self.approval_callback = approval_callback
        self.event_callback = event_callback
        self.last_messages: list[Any] = []
        self._last_snapshot: tuple[int, int] | None = None
        self._started = time.monotonic()

    async def _invoke_graph(
        self,
        value: dict[str, Any] | Command[Any],
        config: RunnableConfig,
    ) -> dict[str, Any]:
        if self.event_callback is None:
            return cast(dict[str, Any], await self.harness.graph.ainvoke(value, config=config))

        latest: dict[str, Any] | None = None
        async for mode, chunk in self.harness.graph.astream(
            value,
            config=config,
            stream_mode=["messages", "values"],
        ):
            if mode == "values" and isinstance(chunk, dict):
                latest = chunk
                self.last_messages = chunk.get("messages", [])
                self._emit_usage_snapshot(self.last_messages)
            elif mode == "messages" and isinstance(chunk, tuple) and chunk:
                message = chunk[0]
                if isinstance(message, AIMessageChunk):
                    text = message.text
                    if text:
                        self.event_callback({"type": "assistant.delta", "text": text})
        if latest is None:
            raise RuntimeError("Graph terminato senza stato finale.")
        return latest

    async def _invoke_with_approval(
        self,
        value: dict[str, Any] | Command[Any],
        config: RunnableConfig,
    ) -> dict[str, Any]:
        result = await self._invoke_graph(value, config)
        while "__interrupt__" in result:
            if self.approval_callback is None:
                raise RuntimeError("Esecuzione sospesa: manca un callback di approvazione.")
            interrupts = result["__interrupt__"]
            payload = interrupts[0].value if interrupts else {}
            approved = await self.approval_callback(payload)
            decision = {"type": "approve"} if approved else {
                "type": "reject",
                "message": "Operazione rifiutata dall'utente.",
            }
            # HumanInTheLoopMiddleware sospende con UN interrupt per turno, ma i tool
            # sensibili chiamati in parallelo nello stesso turno finiscono tutti in
            # `action_requests`: serve una decisione per ciascuno, altrimenti
            # after_model solleva "Number of human decisions does not match number
            # of hanging tool calls". La UI espone una sola conferma per il turno,
            # quindi applichiamo la stessa decisione a ogni tool call in sospeso.
            pending = payload.get("action_requests") if isinstance(payload, dict) else None
            decisions_count = len(pending) if isinstance(pending, list) and pending else 1
            result = await self._invoke_graph(
                Command(resume={"decisions": [decision] * decisions_count}),
                config,
            )
        return result

    async def run(self, goal: str, *, thread_id: str) -> RunResult:
        clean_goal = goal.strip()
        if not clean_goal or len(clean_goal) > 20_000:
            raise ValueError("L'obiettivo deve contenere da 1 a 20.000 caratteri.")
        config: RunnableConfig = {
            "configurable": {"thread_id": thread_id},
            "recursion_limit": 200,
        }
        result = await self._invoke_with_approval(
            {"messages": [{"role": "user", "content": clean_goal}]},
            config,
        )
        maximum = self.harness.settings.harness_max_continuations
        for iteration in range(1, maximum + 1):
            messages = result.get("messages", [])
            text = final_text(messages)
            heuristic_ok = (
                not requires_environment_verification(clean_goal)
                or has_successful_verification(messages)
            )
            feedback = ""
            if text and heuristic_ok:
                grade = await self._grade(clean_goal, text)
                if grade is None or grade.passed:
                    return RunResult(
                        text=text,
                        iterations=iteration,
                        completed=True,
                        messages=messages,
                    )
                feedback = grade.feedback
            if iteration == maximum:
                return RunResult(
                    text=text,
                    iterations=iteration,
                    completed=False,
                    messages=messages,
                )
            if feedback:
                continuation = VERIFICATION_FEEDBACK_PROMPT.format(
                    goal=clean_goal,
                    feedback=feedback,
                    iteration=iteration + 1,
                    maximum=maximum,
                )
            else:
                continuation = CONTINUATION_PROMPT.format(
                    goal=clean_goal,
                    iteration=iteration + 1,
                    maximum=maximum,
                )
            result = await self._invoke_with_approval(
                {"messages": [{"role": "user", "content": continuation}]},
                config,
            )
        raise AssertionError("Ciclo di continuazione terminato in stato impossibile.")

    async def _grade(self, goal: str, answer: str) -> GradeResult | None:
        """Valuta la risposta col grader a rubric, se presente, emettendo eventi trace."""
        grader = self.harness.grader
        if grader is None:
            return None
        self._emit_event({"type": "grader.started"})
        grade = await grader.grade(goal, answer)
        self._emit_event(
            {
                "type": "grader.completed",
                "passed": grade.passed,
                "score": grade.score,
                "feedback": grade.feedback,
                "criteria_scores": grade.criteria_scores,
            }
        )
        return grade

    def _emit_event(self, event: dict[str, Any]) -> None:
        if self.event_callback is not None:
            self.event_callback(event)

    def _emit_usage_snapshot(self, messages: list[Any]) -> None:
        """Emette lo stato del contesto (esatto dal provider) a ogni turno del modello."""
        if self.event_callback is None:
            return
        usage = compute_usage(messages, time.monotonic() - self._started)
        if usage["input_tokens"] == 0 and usage["output_tokens"] == 0:
            return
        snapshot = (usage["input_tokens"], usage["output_tokens"])
        if snapshot == self._last_snapshot:
            return  # niente da segnalare: evita eventi duplicati identici
        self._last_snapshot = snapshot
        self._emit_event({"type": "usage.snapshot", **usage})
