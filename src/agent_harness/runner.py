from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, cast

from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    ToolMessage,
)
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

from agent_harness.factory import Harness
from agent_harness.model_errors import invoke_with_model_retry
from agent_harness.prompts import (
    CONTINUATION_PROMPT,
    FINAL_RESPONSE_FEEDBACK_PROMPT,
    VERIFICATION_FEEDBACK_PROMPT,
)
from agent_harness.run_budget import BudgetExceededError
from agent_harness.usage import compute_usage, token_estimate
from agent_harness.verification import GradeResult

ApprovalCallback = Callable[[dict[str, Any]], Awaitable[bool]]
# Ritorna la risposta dell'utente all'azione richiesta: {"response": str} o {"cancelled": True}.
InteractionCallback = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
RunEventCallback = Callable[[dict[str, Any]], None]


@dataclass
class RunResult:
    text: str
    iterations: int
    completed: bool
    messages: list[BaseMessage]
    terminal_status: str = "completed"
    failure_reason: str = ""


def final_text(messages: list[BaseMessage]) -> str:
    for message in reversed(messages):
        if isinstance(message, AIMessage):
            return message.text
    return ""


# Verbi che segnalano un compito di produzione/modifica di artefatti, quindi da verificare in
# sandbox. Coperte le due lingue del progetto: come il router, non privilegia l'italiano —
# `write a report` e `scrivi un report` devono comportarsi allo stesso modo.
_VERIFICATION_VERBS: tuple[str, ...] = (
    "crea",
    "scrivi",
    "modifica",
    "implementa",
    "correggi",
    "aggiorna",
    "genera",
    "create",
    "write",
    "modify",
    "implement",
    "fix",
    "update",
    "generate",
    "build",
    "refactor",
)


def requires_environment_verification(goal: str) -> bool:
    normalized = goal.casefold()
    return any(verb in normalized for verb in _VERIFICATION_VERBS)


def _current_turn_messages(messages: list[BaseMessage]) -> list[BaseMessage]:
    """I soli messaggi del turno corrente: quelli dopo l'ultimo messaggio umano.

    Senza questo taglio, un ``docker_exec`` andato a buon fine in un obiettivo precedente
    dello stesso thread soddisferebbe la verifica dell'obiettivo attuale — l'intera storia
    del thread è visibile qui.
    """
    for index in range(len(messages) - 1, -1, -1):
        if isinstance(messages[index], HumanMessage):
            return messages[index + 1 :]
    return messages


def has_successful_verification(messages: list[BaseMessage]) -> bool:
    return any(
        isinstance(message, ToolMessage)
        and message.name == "docker_exec"
        and "exit_code=0" in str(message.content)
        for message in _current_turn_messages(messages)
    )


class GoalRunner:
    """Aggiunge approvazione e continuazione limitata al graph dell'agente."""

    def __init__(
        self,
        harness: Harness,
        approval_callback: ApprovalCallback | None = None,
        event_callback: RunEventCallback | None = None,
        interaction_callback: InteractionCallback | None = None,
    ) -> None:
        self.harness = harness
        self.approval_callback = approval_callback
        self.event_callback = event_callback
        self.interaction_callback = interaction_callback
        self.last_messages: list[Any] = []
        self._last_snapshot: tuple[int, int] | None = None
        self._completion_evidence_announced = False
        self._started = time.monotonic()

    def _completion_evidence(self) -> str:
        provider = getattr(self.harness, "completion_evidence", None)
        return provider() if callable(provider) else ""

    def _delegated_environment_verified(self) -> bool:
        check = getattr(self.harness, "delegated_environment_verification", None)
        return bool(check()) if callable(check) else False

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
            interrupts = result["__interrupt__"]
            payload = interrupts[0].value if interrupts else {}
            # Richiesta di azione umana sbloccante (generica: OAuth, upload, codice, ...):
            # il tool ha chiamato interrupt() e attende la risposta dell'utente da inoltrare
            # con Command(resume=...). È distinta dall'approvazione di un tool sensibile.
            if isinstance(payload, dict) and payload.get("type") == "user_action":
                if self.interaction_callback is None:
                    raise RuntimeError("Azione utente richiesta ma manca il callback.")
                response = await self.interaction_callback(payload)
                result = await self._invoke_graph(Command(resume=response), config)
                continue
            if self.approval_callback is None:
                raise RuntimeError("Esecuzione sospesa: manca un callback di approvazione.")
            approved = await self.approval_callback(payload)
            decision = (
                {"type": "approve"}
                if approved
                else {
                    "type": "reject",
                    "message": "Operazione rifiutata dall'utente.",
                }
            )
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
        # Ogni obiettivo riparte dal gradino più economico: l'escalation vale per un obiettivo,
        # non per la sessione. Un compito difficile non rende caro quello che viene dopo.
        self.harness.ladder.reset()
        result = await self._invoke_with_approval(
            {"messages": [{"role": "user", "content": clean_goal}]},
            config,
        )
        maximum = self.harness.settings.harness_max_continuations
        last_failure_reason = ""
        failed_verification = False
        for iteration in range(1, maximum + 1):
            messages = result.get("messages", [])
            text = final_text(messages)
            completion_evidence = self._completion_evidence()
            if completion_evidence and not self._completion_evidence_announced:
                self._completion_evidence_announced = True
                self._emit_event(
                    {
                        "type": "completion.evidence.reused",
                        "chars": len(completion_evidence),
                        "delegated_environment_verification": (
                            self._delegated_environment_verified()
                        ),
                    }
                )
            response_only_retry = False
            checks: list[tuple[bool, str]] = []
            if requires_environment_verification(clean_goal):
                environment_ok = (
                    has_successful_verification(messages) or self._delegated_environment_verified()
                )
                checks.append(
                    (
                        environment_ok,
                        "Manca una verifica sandbox riuscita (`docker_exec`, exit_code=0).",
                    )
                )
            for check in getattr(self.harness, "completion_checks", []):
                checks.append(check(clean_goal, messages))
            check_feedback = [message for passed, message in checks if not passed and message]
            heuristic_ok = all(passed for passed, _ in checks)
            feedback = "\n".join(check_feedback)
            if not heuristic_ok:
                failed_verification = True
                last_failure_reason = feedback or "Verifica finale non superata."
            # Un punteggio sotto la soglia di uscita fa riprovare; solo un punteggio sotto la
            # soglia di escalation dice che il gradino non ce la fa. Fra le due, l'agente
            # riprova con lo stesso modello: costa una iterazione economica invece che una cara.
            fallimento_netto = not heuristic_ok
            if text and heuristic_ok:
                grade = await self._grade(clean_goal, text, completion_evidence)
                if grade is None or grade.passed:
                    return RunResult(
                        text=text,
                        iterations=iteration,
                        completed=True,
                        messages=messages,
                        terminal_status="completed",
                    )
                feedback = grade.feedback
                failed_verification = True
                last_failure_reason = grade.feedback or "Rubric di verifica non superata."
                response_only_retry = bool(
                    completion_evidence
                    and grade.criteria_scores.get("sicurezza", 1.0) >= 0.5
                    and grade.criteria_scores.get("aderenza", 1.0) >= 0.5
                )
                fallimento_netto = (
                    grade.score < self.harness.settings.harness_escalation_threshold
                    and not response_only_retry
                )
            if iteration == maximum:
                return RunResult(
                    text=text,
                    iterations=iteration,
                    completed=False,
                    messages=messages,
                    terminal_status=(
                        "failed_verification" if failed_verification else "incomplete"
                    ),
                    failure_reason=last_failure_reason,
                )
            if feedback and response_only_retry:
                self._emit_event(
                    {
                        "type": "completion.final_response_retry",
                        "iteration": iteration + 1,
                        "reason": feedback,
                    }
                )
                continuation = FINAL_RESPONSE_FEEDBACK_PROMPT.format(
                    feedback=feedback,
                    iteration=iteration + 1,
                    maximum=maximum,
                )
            elif feedback:
                continuation = VERIFICATION_FEEDBACK_PROMPT.format(
                    feedback=feedback,
                    iteration=iteration + 1,
                    maximum=maximum,
                )
            else:
                continuation = CONTINUATION_PROMPT.format(
                    iteration=iteration + 1,
                    maximum=maximum,
                )
            # Il gradino ha fallito nettamente: la continuazione la fa il gradino sopra. È il
            # cuore dell'escalation: non si prevede la difficoltà, la si misura.
            salito = self.harness.ladder.escalate() if fallimento_netto else False
            if self.event_callback is not None:
                if salito:
                    self.event_callback(
                        {
                            "type": "model.escalated",
                            "tier": self.harness.ladder.current,
                            "iteration": iteration + 1,
                        }
                    )
                # Confine tra iterazioni: la UI accumula i delta di streaming e senza questo
                # marcatore concatenerebbe la risposta di ogni continuazione alla precedente.
                self.event_callback({"type": "assistant.iteration", "iteration": iteration + 1})
            result = await self._invoke_with_approval(
                {"messages": [{"role": "user", "content": continuation}]},
                config,
            )
        raise AssertionError("Ciclo di continuazione terminato in stato impossibile.")

    async def _grade(self, goal: str, answer: str, evidence: str = "") -> GradeResult | None:
        """Valuta la risposta col grader a rubric, se presente, emettendo eventi trace."""
        grader = self.harness.grader
        if grader is None:
            return None
        self._emit_event({"type": "grader.started"})
        reservation = None
        tracker = getattr(self.harness, "budget_tracker", None)
        grader_rate = getattr(self.harness, "grader_rate", None)
        if tracker is not None and grader_rate is not None:
            reservation = tracker.before_model_call(
                kind="grader",
                rate=grader_rate,
                estimated_input_tokens=(
                    token_estimate(goal) + token_estimate(answer) + token_estimate(evidence) + 1_000
                ),
            )
        try:
            grade = await invoke_with_model_retry(
                lambda: (
                    grader.grade_with_evidence(goal, answer, evidence)
                    if evidence and hasattr(grader, "grade_with_evidence")
                    else grader.grade(goal, answer)
                ),
                event_callback=self.event_callback,
                call_kind="grader",
                model=getattr(grader_rate, "model", "grader"),
                on_retry=(
                    (lambda _exc, _details: tracker.record_retry_estimate(reservation))
                    if reservation is not None and tracker is not None
                    else None
                ),
            )
            if reservation is not None and tracker is not None:
                tracker.record_estimated_call(reservation, grade)
        except BudgetExceededError:
            raise
        except Exception:
            if reservation is not None and tracker is not None:
                tracker.cancel_model_call(reservation)
            raise
        self._emit_event(
            {
                "type": "grader.completed",
                "passed": grade.passed,
                "score": grade.score,
                "feedback": grade.feedback,
                "criteria_scores": grade.criteria_scores,
                "safety_vetoed": grade.safety_vetoed,
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
