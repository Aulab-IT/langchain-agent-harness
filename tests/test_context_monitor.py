from __future__ import annotations

from types import SimpleNamespace

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from agent_harness.context_monitor import (
    ContextMonitorMiddleware,
    context_snapshot,
    detect_compaction,
)


def test_snapshot_counts_and_categorizes() -> None:
    messages = [
        HumanMessage(content="analizza il csv"),
        AIMessage(content="procedo"),
        ToolMessage(content="riga1\nriga2", tool_call_id="t1", name="docker_exec"),
    ]
    snap = context_snapshot(messages, "system prompt", window_tokens=1000)
    assert snap.total_tokens > 0
    assert snap.message_count == 3
    assert "System & memoria" in snap.categories
    assert "Conversazione" in snap.categories
    assert "Tool output" in snap.categories
    assert 0 <= snap.fill_ratio <= 1


def test_fill_ratio_scales_with_window() -> None:
    messages = [HumanMessage(content="x" * 4000)]
    small = context_snapshot(messages, "", window_tokens=1000)
    large = context_snapshot(messages, "", window_tokens=100_000)
    assert small.fill_ratio > large.fill_ratio


def test_detect_compaction_on_sharp_drop() -> None:
    assert detect_compaction(10_000, 3_000) is True
    assert detect_compaction(10_000, 9_000) is False
    assert detect_compaction(0, 5_000) is False


def test_middleware_emits_snapshot_and_pressure() -> None:
    events: list[dict] = []
    mw = ContextMonitorMiddleware(
        window_tokens=100,
        event_callback=events.append,
        warning_ratio=0.7,
        compaction_ratio=0.8,
    )

    request = SimpleNamespace(
        messages=[HumanMessage(content="x" * 4000)],
        system_message=SystemMessage(content="sys"),
    )
    mw._observe(request)
    snapshots = [e for e in events if e["type"] == "context.snapshot"]
    assert snapshots
    # Un contesto enorme in una finestra minuscola è sotto forte pressione.
    assert snapshots[-1]["pressure"] == "high"


def test_middleware_detects_compaction_across_calls() -> None:
    events: list[dict] = []
    mw = ContextMonitorMiddleware(window_tokens=100_000, event_callback=events.append)

    big = SimpleNamespace(messages=[HumanMessage(content="x" * 40_000)], system_message=None)
    small = SimpleNamespace(messages=[HumanMessage(content="x" * 4_000)], system_message=None)

    mw._observe(big)
    mw._observe(small)
    detected = [e for e in events if e["type"] == "context.compaction.detected"]
    assert detected
    assert detected[0]["tokens_reclaimed"] > 0
