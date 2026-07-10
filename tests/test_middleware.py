from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from agent_harness.middleware import decide_model


def test_tool_output_does_not_decide_the_model() -> None:
    """Il bug del router precedente: `messages[-1]` è quasi sempre un ToolMessage."""
    messages = [
        HumanMessage("quanto fa 2 + 2?"),
        AIMessage("controllo"),
        ToolMessage("il file parla di un refactor complesso", tool_call_id="1"),
    ]

    decision = decide_model(messages)

    assert decision.choice == "default"
    assert decision.source == "default"


def test_keyword_in_the_human_message_selects_the_strong_model() -> None:
    decision = decide_model([HumanMessage("fammi un refactor del modulo")])

    assert decision.choice == "strong"
    assert decision.source == "keyword"
    assert "refactor" in decision.reason


def test_english_keywords_are_recognized() -> None:
    assert decide_model([HumanMessage("explain the architecture")]).choice == "strong"


def test_decision_follows_the_latest_human_message_not_the_first() -> None:
    messages = [
        HumanMessage("fammi un refactor complesso"),
        AIMessage("fatto"),
        HumanMessage("che ore sono?"),
    ]

    assert decide_model(messages).choice == "default"


def test_session_override_beats_the_keyword() -> None:
    decision = decide_model(
        [HumanMessage("fammi un refactor")],
        session_override="default",
    )

    assert decision.choice == "default"
    assert decision.source == "session_override"


def test_message_override_beats_the_session_override() -> None:
    decision = decide_model(
        [HumanMessage("che ore sono? [Modello: forte]")],
        session_override="default",
    )

    assert decision.choice == "strong"
    assert decision.source == "message_override"


def test_message_override_can_force_the_default_model() -> None:
    decision = decide_model(
        [HumanMessage("fammi un refactor complesso [Modello: base]")],
        session_override="strong",
    )

    assert decision.choice == "default"


def test_long_conversations_fall_back_to_the_strong_model() -> None:
    messages: list[object] = [HumanMessage("ciao")]
    messages.extend(AIMessage("ok") for _ in range(45))
    messages.append(HumanMessage("e adesso?"))

    decision = decide_model(messages)  # type: ignore[arg-type]

    assert decision.choice == "strong"
    assert decision.source == "context_size"


def test_multimodal_human_content_is_read_as_text() -> None:
    message = HumanMessage(
        content=[
            {"type": "text", "text": "guarda l'architettura"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,x"}},
        ]
    )

    assert decide_model([message]).choice == "strong"


def test_no_human_message_yields_the_default_model() -> None:
    assert decide_model([AIMessage("solo io")]).choice == "default"


def test_empty_history_yields_the_default_model() -> None:
    assert decide_model([]).choice == "default"
