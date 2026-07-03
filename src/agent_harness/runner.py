from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, cast

from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

from agent_harness.factory import Harness
from agent_harness.prompts import CONTINUATION_PROMPT

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
            result = await self._invoke_graph(
                Command(resume={"decisions": [decision]}),
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
            verified = (
                not requires_environment_verification(clean_goal)
                or has_successful_verification(messages)
            )
            if text and verified:
                return RunResult(
                    text=text,
                    iterations=iteration,
                    completed=True,
                    messages=messages,
                )
            if iteration == maximum:
                return RunResult(
                    text=text,
                    iterations=iteration,
                    completed=False,
                    messages=messages,
                )
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
