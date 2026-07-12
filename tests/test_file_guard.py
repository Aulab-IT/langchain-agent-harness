from __future__ import annotations

import base64

from langchain_core.messages import HumanMessage, ToolMessage

from agent_harness.file_guard import _is_corrupt_file_block, sanitize_messages


def _pdf_block(raw: bytes) -> dict:
    return {
        "type": "file",
        "base64": base64.b64encode(raw).decode(),
        "mime_type": "application/pdf",
    }


def test_corrupt_pdf_block_is_detected() -> None:
    assert _is_corrupt_file_block(_pdf_block(b"test")) is True
    assert _is_corrupt_file_block(_pdf_block(b"%PDF-1.4\ncontenuto")) is False


def test_unknown_mime_is_left_alone() -> None:
    # Non sappiamo validare questo tipo: lo lasciamo passare invariato.
    block = {"type": "image", "base64": base64.b64encode(b"x").decode(), "mime_type": "image/png"}
    assert _is_corrupt_file_block(block) is False


def test_bad_base64_is_treated_as_corrupt() -> None:
    assert _is_corrupt_file_block({"mime_type": "application/pdf", "base64": 123}) is False


def test_sanitize_replaces_only_corrupt_blocks() -> None:
    good = _pdf_block(b"%PDF-1.4 ok")
    bad = _pdf_block(b"test")
    messages = [
        HumanMessage(content="ciao"),
        ToolMessage(content=[bad, {"type": "text", "text": "nota"}], tool_call_id="a"),
        ToolMessage(content=[good], tool_call_id="b"),
    ]
    cleaned_messages, count = sanitize_messages(messages)
    assert count == 1
    # Il blocco corrotto è diventato una nota testuale; la nota preesistente resta.
    first = cleaned_messages[1].content
    assert first[0]["type"] == "text" and "rimosso" in first[0]["text"]
    assert first[1] == {"type": "text", "text": "nota"}
    # Il PDF valido non viene toccato.
    assert cleaned_messages[2].content[0]["mime_type"] == "application/pdf"
    # I messaggi senza blocchi passano per riferimento (nessuna copia inutile).
    assert cleaned_messages[0] is messages[0]


def test_sanitize_no_op_when_nothing_corrupt() -> None:
    messages = [HumanMessage(content="testo semplice")]
    cleaned_messages, count = sanitize_messages(messages)
    assert count == 0
    assert cleaned_messages[0] is messages[0]
