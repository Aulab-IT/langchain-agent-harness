from pathlib import Path

from agent_harness.tools import build_tools, current_utc_time


def test_tools_can_disable_web_search(tmp_path: Path) -> None:
    names = {
        tool.name
        for tool in build_tools(
            tmp_path,
            session_id="test-session",
            enable_web_search=False,
            enable_browser=False,
            output_limit=2_000,
        )
    }
    assert names == {"current_utc_time", "docker_exec", "request_user_action"}


def test_time_tool_returns_iso_timestamp() -> None:
    value = current_utc_time.invoke({})
    assert "T" in value
    assert "+00:00" in value
