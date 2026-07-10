from unittest.mock import patch

from agent_harness.interaction import request_user_action, user_action_tool


def test_tool_metadata() -> None:
    tool = user_action_tool()
    assert tool.name == "request_user_action"
    assert "response_kind" in tool.args


@patch("agent_harness.interaction.interrupt")
def test_request_emits_user_action_payload(interrupt) -> None:
    interrupt.return_value = {"response": "code-123"}
    request_user_action("Autorizza", "Apri il link e incolla il codice", "value", "https://x")
    payload = interrupt.call_args.args[0]
    assert payload["type"] == "user_action"
    assert payload["response_kind"] == "value"
    assert payload["url"] == "https://x"


@patch("agent_harness.interaction.interrupt")
def test_value_response_is_returned_to_agent(interrupt) -> None:
    interrupt.return_value = {"response": "abc-token"}
    result = request_user_action("t", "i", "value")
    assert "abc-token" in result


@patch("agent_harness.interaction.interrupt")
def test_confirm_response(interrupt) -> None:
    interrupt.return_value = {"response": ""}
    result = request_user_action("t", "i", "confirm")
    assert "confermato" in result.lower()


@patch("agent_harness.interaction.interrupt")
def test_cancel_response(interrupt) -> None:
    interrupt.return_value = {"cancelled": True}
    result = request_user_action("t", "i", "confirm")
    assert "annullato" in result.lower()
