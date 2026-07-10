from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from agent_harness.config import SANDBOX_SKILLS_MOUNT, SANDBOX_WORKSPACE_MOUNT
from agent_harness.prompts import SYSTEM_PROMPT

CATEGORY_COLORS = {
    "System & memoria": "#60a5fa",
    "Conversazione": "#8b5cf6",
    "File letti": "#34d399",
    "Skills": "#f472b6",
    "Tool output": "#f59e0b",
}


def token_estimate(value: Any) -> int:
    if isinstance(value, str):
        return max(0, round(len(value) / 4))
    return max(0, round(len(json.dumps(value, ensure_ascii=False)) / 4))


def context_categories(messages: list[Any]) -> list[dict[str, Any]]:
    totals = {
        "System & memoria": token_estimate(SYSTEM_PROMPT),
        "Conversazione": 0,
        "File letti": 0,
        "Skills": 0,
        "Tool output": 0,
    }
    tool_paths: dict[str, str] = {}
    for message in messages:
        if isinstance(message, AIMessage):
            totals["Conversazione"] += token_estimate(message.text)
            for call in message.tool_calls:
                arguments = call.get("args", {})
                path = arguments.get("file_path") or arguments.get("path")
                if isinstance(path, str):
                    tool_paths[str(call.get("id", ""))] = path
        elif isinstance(message, HumanMessage):
            totals["Conversazione"] += token_estimate(message.content)
        elif isinstance(message, SystemMessage):
            totals["System & memoria"] += token_estimate(message.content)
        elif isinstance(message, ToolMessage):
            estimated = token_estimate(message.content)
            path = tool_paths.get(message.tool_call_id, "")
            if path.startswith(f"{SANDBOX_SKILLS_MOUNT}/"):
                totals["Skills"] += estimated
            elif path.startswith(f"{SANDBOX_WORKSPACE_MOUNT}/"):
                totals["File letti"] += estimated
            else:
                totals["Tool output"] += estimated
    denominator = max(sum(totals.values()), 1)
    return [
        {
            "name": name,
            "tokens": tokens,
            "percent": round(tokens / denominator * 100),
            "color": CATEGORY_COLORS[name],
        }
        for name, tokens in totals.items()
    ]


def token_metrics(messages: list[Any]) -> dict[str, int]:
    """Le tre grandezze token tenute distinte, direttamente dai messaggi.

    - ``context_input_tokens``: input dell'ULTIMA chiamata al modello, cioè la
      dimensione del contesto a fine run. Ogni ``usage_metadata.input_tokens`` del
      provider include già tutta la storia fino a quel punto, quindi è l'ultimo valore
      a rappresentare il contesto, non la somma;
    - ``cumulative_input_tokens``: somma degli input di tutte le chiamate, cioè quanto
      contesto è stato letto complessivamente nel run (misura di costo, non di finestra);
    - ``cumulative_output_tokens``: somma degli output, token nuovi che non si ripetono.

    Confondere le prime due è il bug che la Fase 0 elimina: la UI mostrava il contesto
    finale, l'eval sommava gli input, ed entrambi li chiamavano "input_tokens".
    """
    context_input = 0
    cumulative_input = 0
    cumulative_output = 0
    reasoning = 0
    for message in messages:
        if not isinstance(message, AIMessage) or not message.usage_metadata:
            continue
        metadata = message.usage_metadata
        context_input = int(metadata.get("input_tokens", 0))
        cumulative_input += int(metadata.get("input_tokens", 0))
        cumulative_output += int(metadata.get("output_tokens", 0))
        details = metadata.get("output_token_details") or {}
        reasoning += int(details.get("reasoning", 0) or 0)
    return {
        "context_input_tokens": context_input,
        "cumulative_input_tokens": cumulative_input,
        "cumulative_output_tokens": cumulative_output,
        "reasoning_tokens": reasoning,
    }


def compute_usage(messages: list[Any], elapsed_seconds: float) -> dict[str, Any]:
    """Costruisce l'usage del run.

    ``input_tokens`` riflette la dimensione del contesto all'ultima chiamata al modello
    (retro-compatibile con la UI), mentre i campi ``*_input_tokens`` separati distinguono
    esplicitamente contesto finale e somma cumulativa: vedi :func:`token_metrics`.
    """
    metrics = token_metrics(messages)
    input_tokens = metrics["context_input_tokens"]
    output_tokens = metrics["cumulative_output_tokens"]
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "output_tokens_per_second": round(output_tokens / max(elapsed_seconds, 0.001), 1),
        "context_categories": context_categories(messages),
        "estimated_context": False,
        # Grandezze canoniche separate (Fase 0): il contesto finale non è la somma degli
        # input, e chi vuole il costo cumulativo deve leggere il campo cumulativo.
        "context_input_tokens": metrics["context_input_tokens"],
        "cumulative_input_tokens": metrics["cumulative_input_tokens"],
        "cumulative_output_tokens": metrics["cumulative_output_tokens"],
        "reasoning_tokens": metrics["reasoning_tokens"],
    }
