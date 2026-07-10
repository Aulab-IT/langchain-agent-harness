from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from agent_harness.middleware import TierLadder, decide_tier


def test_the_first_attempt_uses_the_cheapest_tier() -> None:
    """Non si predice la difficoltà: si parte in basso e si lascia provare."""
    decision = decide_tier([HumanMessage("rifammi l'architettura del modulo")], TierLadder())

    assert decision.tier == "low"
    assert decision.source == "default"


def test_no_keyword_can_raise_the_tier_in_any_language() -> None:
    """Il buco che aveva il router a parole chiave: `analyze` non c'era, `analizza` sì."""
    for testo in (
        "analizza il csv",
        "analyze the csv file",
        "analiza el csv",
        "analysiere die CSV-Datei",
        "refactor this class",
    ):
        assert decide_tier([HumanMessage(testo)], TierLadder()).tier == "low"


def test_a_tool_output_cannot_move_the_tier() -> None:
    messages = [
        HumanMessage("quanto fa 2 + 2?"),
        AIMessage("controllo"),
        ToolMessage("il file parla di un refactor complesso", tool_call_id="1"),
    ]

    assert decide_tier(messages, TierLadder()).tier == "low"


def test_escalation_climbs_one_rung_per_failed_iteration() -> None:
    ladder = TierLadder()

    assert ladder.escalate() is True
    decision = decide_tier([HumanMessage("riprova")], ladder)
    assert decision.tier == "mid"
    assert decision.source == "escalation"
    assert "criterio di uscita" in decision.reason

    assert ladder.escalate() is True
    assert decide_tier([HumanMessage("riprova")], ladder).tier == "high"


def test_the_ladder_stops_at_the_top_rather_than_wrapping_around() -> None:
    ladder = TierLadder()
    ladder.escalate()
    ladder.escalate()

    assert ladder.current == "high"
    assert ladder.escalate() is False
    assert ladder.current == "high"


def test_a_new_goal_starts_again_from_the_bottom() -> None:
    """L'escalation vale per un obiettivo, non per la sessione."""
    ladder = TierLadder()
    ladder.escalate()
    ladder.escalate()

    ladder.reset()

    assert ladder.current == "low"
    assert decide_tier([HumanMessage("nuovo obiettivo")], ladder).tier == "low"


def test_session_override_beats_the_escalation() -> None:
    ladder = TierLadder()
    ladder.escalate()  # sarebbe "mid"

    decision = decide_tier([HumanMessage("riprova")], ladder, session_override="low")

    assert decision.tier == "low"
    assert decision.source == "session_override"


def test_message_marker_beats_the_session_override() -> None:
    decision = decide_tier(
        [HumanMessage("che ore sono? [Modello: alto]")],
        TierLadder(),
        session_override="low",
    )

    assert decision.tier == "high"
    assert decision.source == "message_override"


def test_markers_from_the_old_binary_scale_still_resolve() -> None:
    """Quei marcatori sono già nei messaggi salvati: non possiamo smettere di capirli."""
    assert decide_tier([HumanMessage("x [Modello: forte]")], TierLadder()).tier == "high"
    assert decide_tier([HumanMessage("x [Modello: base]")], TierLadder()).tier == "low"
    assert decide_tier([HumanMessage("x [Modello: medio]")], TierLadder()).tier == "mid"


def test_the_marker_is_read_from_the_last_human_message_only() -> None:
    messages = [
        HumanMessage("primo [Modello: alto]"),
        AIMessage("ok"),
        HumanMessage("secondo"),
    ]

    assert decide_tier(messages, TierLadder()).tier == "low"


def test_multimodal_human_content_is_read_as_text() -> None:
    message = HumanMessage(
        content=[
            {"type": "text", "text": "ciao [Modello: alto]"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,x"}},
        ]
    )

    assert decide_tier([message], TierLadder()).tier == "high"


def test_no_human_message_yields_the_cheapest_tier() -> None:
    assert decide_tier([AIMessage("solo io")], TierLadder()).tier == "low"


def test_empty_history_yields_the_cheapest_tier() -> None:
    assert decide_tier([], TierLadder()).tier == "low"
