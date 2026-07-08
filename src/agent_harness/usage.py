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


def compute_usage(messages: list[Any], elapsed_seconds: float) -> dict[str, Any]:
    """Costruisce l'usage del run.

    ``input_tokens`` riflette la dimensione del contesto all'ultima chiamata
    al modello, non la somma delle chiamate: ogni ``usage_metadata.input_tokens``
    del provider include già l'intera storia della conversazione fino a quel
    punto, quindi sommarli tra più turni gonfia il conteggio ben oltre la
    finestra di contesto reale. ``output_tokens`` invece è correttamente una
    somma, perché ogni turno genera token nuovi che non si ripetono.
    """
    input_tokens = 0
    output_tokens = 0
    for message in messages:
        if not isinstance(message, AIMessage) or not message.usage_metadata:
            continue
        input_tokens = int(message.usage_metadata.get("input_tokens", 0))
        output_tokens += int(message.usage_metadata.get("output_tokens", 0))
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "output_tokens_per_second": round(output_tokens / max(elapsed_seconds, 0.001), 1),
        "context_categories": context_categories(messages),
        "estimated_context": False,
    }
