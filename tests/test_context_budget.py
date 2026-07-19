from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from langchain.agents.middleware import ModelRequest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from agent_harness.config import Settings
from agent_harness.context_budget import (
    OFFLOAD_MARKER,
    ContextAction,
    ContextBudget,
    ContextBudgetManager,
    LiveUsageThrottle,
    StructuredSummary,
    ToolOutputOffloadMiddleware,
    context_budget_from_settings,
    drop_reconstructible,
    offload_tool_output,
)


def _tool(content: str, call_id: str = "c1") -> ToolMessage:
    return ToolMessage(content=content, tool_call_id=call_id)


def test_budget_usable_reserves_output() -> None:
    budget = ContextBudget(max_tokens=10_000, reserved_output_tokens=2_000)
    assert budget.usable_tokens == 8_000


def test_inspect_measures_fill_and_categories() -> None:
    manager = ContextBudgetManager()
    budget = ContextBudget(max_tokens=1_000, reserved_output_tokens=0)
    messages = [SystemMessage(content="x" * 400), _tool("y" * 400)]
    snapshot = manager.inspect(messages, budget)
    assert snapshot.total_tokens == 200  # 800 chars / 4
    assert snapshot.tool_output_tokens == 100
    assert 0.19 <= snapshot.fill_ratio <= 0.21


def test_decide_keeps_when_below_warning() -> None:
    manager = ContextBudgetManager()
    budget = ContextBudget(max_tokens=10_000, reserved_output_tokens=0)
    snapshot = manager.inspect([SystemMessage(content="short")], budget)
    assert manager.decide(snapshot, budget) == ContextAction.KEEP


def test_decide_offloads_long_tool_output_over_compaction() -> None:
    manager = ContextBudgetManager(tool_output_soft_limit=50)
    budget = ContextBudget(max_tokens=400, reserved_output_tokens=0)
    # Un output di tool lungo che riempie oltre la soglia di compaction.
    messages = [_tool("z" * 1_400)]
    snapshot = manager.inspect(messages, budget)
    assert snapshot.reconstructible_tokens > 0
    assert manager.decide(snapshot, budget) == ContextAction.OFFLOAD_TOOL_OUTPUT


def test_offloaded_output_is_not_reconstructible_again() -> None:
    manager = ContextBudgetManager(tool_output_soft_limit=50)
    budget = ContextBudget(max_tokens=400, reserved_output_tokens=0)
    offloaded = _tool(f"{OFFLOAD_MARKER} ref=file sha256=abc " + "z" * 1_400)
    snapshot = manager.inspect([offloaded], budget)
    assert snapshot.reconstructible_tokens == 0


def test_offload_produces_reference_checksum_excerpt() -> None:
    result = offload_tool_output("A" * 2_000, reference="/workspace/out.txt", excerpt_chars=100)
    assert result.reference == "/workspace/out.txt"
    assert len(result.checksum) == 16
    assert result.excerpt.endswith("…")
    assert OFFLOAD_MARKER in result.render()


def test_drop_reconstructible_keeps_last_observation() -> None:
    messages = [
        HumanMessage(content="go"),
        _tool("first", "c1"),
        AIMessage(content="thinking"),
        _tool("second", "c1"),
    ]
    kept = drop_reconstructible(messages)
    tool_contents = [m.content for m in kept if isinstance(m, ToolMessage)]
    assert tool_contents == ["second"]
    assert len(kept) == 3


def test_structured_summary_renders_schema() -> None:
    summary = StructuredSummary(
        goal="fix bug",
        constraints=["no network"],
        decisions=["use retry"],
        open_items=["verify"],
        artifacts=[{"path": "out.txt", "checksum": "abc"}],
    )
    rendered = summary.render()
    assert "goal: fix bug" in rendered
    assert "constraints:" in rendered
    assert "path: out.txt" in rendered


def test_live_usage_throttle_limits_rate() -> None:
    throttle = LiveUsageThrottle(min_interval_seconds=1.0)
    assert throttle.offer({"t": 1}, now=0.0) == {"t": 1}  # primo passa
    assert throttle.offer({"t": 2}, now=0.3) is None  # troppo presto
    assert throttle.offer({"t": 3}, now=0.5) is None
    assert throttle.offer({"t": 4}, now=1.1) == {"t": 4}  # oltre l'intervallo
    # Dopo un'offerta soppressa, flush emette l'ultimo valore trattenuto.
    assert throttle.offer({"t": 5}, now=1.2) is None
    assert throttle.flush() == {"t": 5}
    assert throttle.flush() is None


def test_context_budget_from_settings_applies_window() -> None:
    settings = Settings(_env_file=None, harness_context_window=64_000)
    budget = context_budget_from_settings(settings)
    assert budget.max_tokens == 64_000
    assert budget.warning_ratio == settings.harness_context_warning_ratio


@pytest.mark.asyncio
async def test_long_tool_output_is_replaced_and_saved(tmp_path: Path) -> None:
    middleware = ToolOutputOffloadMiddleware(tmp_path, soft_limit_tokens=100)
    original = "scientific result\n" * 500
    message = ToolMessage(content=original, tool_call_id="call-1", name="browser_read")
    request = ModelRequest(  # type: ignore[arg-type]
        model=SimpleNamespace(), messages=[message], tools=[]
    )
    captured: ModelRequest | None = None

    async def handler(next_request: ModelRequest) -> object:
        nonlocal captured
        captured = next_request
        return object()

    await middleware.awrap_model_call(request, handler)  # type: ignore[arg-type]

    assert captured is not None
    reduced = captured.messages[0]
    assert isinstance(reduced, ToolMessage)
    assert reduced.tool_call_id == "call-1"
    assert OFFLOAD_MARKER in str(reduced.content)
    saved = list((tmp_path / ".context" / "tool-output").glob("*.txt"))
    assert len(saved) == 1
    assert saved[0].read_text(encoding="utf-8") == original


@pytest.mark.asyncio
async def test_short_or_already_offloaded_tool_output_is_untouched(tmp_path: Path) -> None:
    middleware = ToolOutputOffloadMiddleware(tmp_path, soft_limit_tokens=100)
    messages = [
        _tool("short", "one"),
        _tool(f"{OFFLOAD_MARKER} ref=/workspace/already", "two"),
    ]
    request = ModelRequest(  # type: ignore[arg-type]
        model=SimpleNamespace(), messages=messages, tools=[]
    )

    async def handler(next_request: ModelRequest) -> object:
        assert next_request is request
        return object()

    await middleware.awrap_model_call(request, handler)  # type: ignore[arg-type]
    assert not (tmp_path / ".context").exists()


# --- validazione delle soglie ---------------------------------------------------------


def test_budget_rejects_unordered_ratios() -> None:
    # Con warning sopra compaction la zona di allerta non esisterebbe: `decide` la
    # salterebbe in silenzio invece di offloadare prima di comprimere.
    with pytest.raises(ValueError, match="Soglie non ordinate"):
        ContextBudget(max_tokens=100_000, warning_ratio=0.9, compaction_ratio=0.8)


def test_budget_accepts_equal_ratios() -> None:
    budget = ContextBudget(
        max_tokens=100_000, warning_ratio=0.8, compaction_ratio=0.8, hard_ratio=0.8
    )
    assert budget.compaction_ratio == 0.8


def test_budget_rejects_ratio_outside_unit_interval() -> None:
    with pytest.raises(ValueError, match="hard_ratio"):
        ContextBudget(max_tokens=100_000, hard_ratio=1.5)
    with pytest.raises(ValueError, match="warning_ratio"):
        ContextBudget(max_tokens=100_000, warning_ratio=0)


def test_budget_rejects_reservation_that_leaves_no_window() -> None:
    with pytest.raises(ValueError, match="lasciare spazio"):
        ContextBudget(max_tokens=4_000, reserved_output_tokens=4_000)


def test_budget_rejects_non_positive_window() -> None:
    with pytest.raises(ValueError, match="max_tokens"):
        ContextBudget(max_tokens=0)
