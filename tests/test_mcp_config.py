from __future__ import annotations

from pathlib import Path

import pytest

from agent_harness.mcp_config import (
    BUILTIN_SERVER,
    expand_env,
    load_user_config_text,
    merged_connections,
    save_user_config,
    validate_user_config,
)


def test_expand_env_replaces_known_and_keeps_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TOKEN_A", "secret")
    result = expand_env({"h": "Bearer ${TOKEN_A}", "x": "${MISSING}"})
    assert result["h"] == "Bearer secret"
    # Una variabile assente resta riferimento letterale, non stringa vuota.
    assert result["x"] == "${MISSING}"


def test_validate_stdio_server() -> None:
    raw = {"mcpServers": {"echo": {"command": "python", "args": ["-m", "echo"]}}}
    validation = validate_user_config(raw)
    assert validation.problems == []
    assert validation.connections["echo"]["transport"] == "stdio"
    assert validation.connections["echo"]["command"] == "python"


def test_validate_remote_server_infers_streamable_http() -> None:
    raw = {"mcpServers": {"linear": {"url": "https://mcp.linear.app"}}}
    validation = validate_user_config(raw)
    assert validation.problems == []
    assert validation.connections["linear"]["transport"] == "streamable_http"


def test_reserved_builtin_name_is_rejected() -> None:
    raw = {"mcpServers": {BUILTIN_SERVER: {"command": "python"}}}
    validation = validate_user_config(raw)
    assert validation.connections == {}
    assert any("riservato" in problem for problem in validation.problems)


def test_server_without_command_or_url_is_rejected() -> None:
    validation = validate_user_config({"mcpServers": {"bad": {"args": []}}})
    assert validation.connections == {}
    assert validation.problems


def test_command_and_url_together_is_rejected() -> None:
    validation = validate_user_config(
        {"mcpServers": {"bad": {"command": "x", "url": "https://y"}}}
    )
    assert validation.connections == {}
    assert validation.problems


def test_invalid_transport_is_rejected() -> None:
    validation = validate_user_config(
        {"mcpServers": {"x": {"url": "https://y", "transport": "carrier-pigeon"}}}
    )
    assert validation.connections == {}
    assert validation.problems


def test_save_rejects_broken_json_and_does_not_write(tmp_path: Path) -> None:
    validation = save_user_config(tmp_path, "{not json")
    assert validation.problems
    assert not (tmp_path / "mcp.json").exists()


def test_save_rejects_invalid_config_and_does_not_write(tmp_path: Path) -> None:
    validation = save_user_config(tmp_path, '{"mcpServers": {"bad": {}}}')
    assert validation.problems
    assert not (tmp_path / "mcp.json").exists()


def test_save_valid_config_writes_atomically(tmp_path: Path) -> None:
    text = '{"mcpServers": {"echo": {"command": "python"}}}'
    validation = save_user_config(tmp_path, text)
    assert validation.problems == []
    assert (tmp_path / "mcp.json").is_file()
    assert "echo" in load_user_config_text(tmp_path)


def test_merged_always_includes_builtin_and_user_servers(tmp_path: Path) -> None:
    save_user_config(tmp_path, '{"mcpServers": {"echo": {"command": "python"}}}')
    connections = merged_connections(tmp_path, tmp_path, tmp_path)
    assert BUILTIN_SERVER in connections
    assert "echo" in connections
    assert connections[BUILTIN_SERVER]["transport"] == "stdio"


def test_missing_config_yields_no_user_servers(tmp_path: Path) -> None:
    connections = merged_connections(tmp_path, tmp_path, tmp_path)
    assert set(connections) == {BUILTIN_SERVER}
