from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from agent_harness.middleware import decide_tier


def test_tool_output_does_not_decide_the_tier() -> None:
    """Il bug del router precedente: `messages[-1]` è quasi sempre un ToolMessage."""
    messages = [
        HumanMessage("quanto fa 2 + 2?"),
        AIMessage("controllo"),
        ToolMessage("il file parla di un refactor complesso", tool_call_id="1"),
    ]

    decision = decide_tier(messages)

    assert decision.tier == "low"
    assert decision.source == "default"


def test_an_ordinary_request_stays_on_the_cheapest_tier() -> None:
    """La regola di costo: si sta in basso finché qualcosa non dice di salire."""
    assert decide_tier([HumanMessage("che ore sono?")]).tier == "low"


def test_a_high_keyword_climbs_two_rungs() -> None:
    decision = decide_tier([HumanMessage("fammi un refactor del modulo")])

    assert decision.tier == "high"
    assert decision.source == "keyword"
    assert "refactor" in decision.reason


def test_a_mid_keyword_climbs_one_rung_only() -> None:
    decision = decide_tier([HumanMessage("analizza il csv e dimmi la media")])

    assert decision.tier == "mid"
    assert decision.source == "keyword"


def test_high_keywords_win_over_mid_keywords() -> None:
    """Il testo contiene entrambi: vince il segnale più forte, non il primo trovato."""
    decision = decide_tier([HumanMessage("analizza l'architettura del progetto")])

    assert decision.tier == "high"


def test_english_keywords_are_recognized_on_both_rungs() -> None:
    assert decide_tier([HumanMessage("explain the architecture")]).tier == "high"
    assert decide_tier([HumanMessage("compare the two files")]).tier == "mid"


def test_decision_follows_the_latest_human_message_not_the_first() -> None:
    messages = [
        HumanMessage("fammi un refactor complesso"),
        AIMessage("fatto"),
        HumanMessage("che ore sono?"),
    ]

    assert decide_tier(messages).tier == "low"


def test_a_long_conversation_climbs_one_rung_not_two() -> None:
    """La lunghezza è un indizio debole: pagarla al gradino alto non si giustifica."""
    messages: list[object] = [HumanMessage("ciao")]
    messages.extend(AIMessage("ok") for _ in range(45))
    messages.append(HumanMessage("e adesso?"))

    decision = decide_tier(messages)  # type: ignore[arg-type]

    assert decision.tier == "mid"
    assert decision.source == "context_size"


def test_session_override_beats_the_keywords() -> None:
    decision = decide_tier([HumanMessage("fammi un refactor")], session_override="low")

    assert decision.tier == "low"
    assert decision.source == "session_override"


def test_message_override_beats_the_session_override() -> None:
    decision = decide_tier(
        [HumanMessage("che ore sono? [Modello: alto]")],
        session_override="low",
    )

    assert decision.tier == "high"
    assert decision.source == "message_override"


def test_message_override_reaches_the_middle_rung() -> None:
    assert decide_tier([HumanMessage("ciao [Modello: medio]")]).tier == "mid"


def test_message_override_can_force_the_cheapest_tier() -> None:
    decision = decide_tier(
        [HumanMessage("fammi un refactor complesso [Modello: basso]")],
        session_override="high",
    )

    assert decision.tier == "low"


def test_markers_from_the_old_binary_scale_still_resolve() -> None:
    """Quei marcatori sono già nei messaggi salvati: non possiamo smettere di capirli."""
    assert decide_tier([HumanMessage("x [Modello: forte]")]).tier == "high"
    assert decide_tier([HumanMessage("x [Modello: base]")]).tier == "low"


def test_multimodal_human_content_is_read_as_text() -> None:
    message = HumanMessage(
        content=[
            {"type": "text", "text": "guarda l'architettura"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,x"}},
        ]
    )

    assert decide_tier([message]).tier == "high"


def test_no_human_message_yields_the_cheapest_tier() -> None:
    assert decide_tier([AIMessage("solo io")]).tier == "low"


def test_empty_history_yields_the_cheapest_tier() -> None:
    assert decide_tier([]).tier == "low"
