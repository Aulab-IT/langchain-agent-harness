from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from agent_harness.sandbox import DockerSandbox, SessionSandboxManager


def test_docker_run_flags_have_security_boundaries(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    manager = SessionSandboxManager()
    command = manager.run_flags(workspace, "langchain-harness-sandbox:latest")
    joined = " ".join(command)
    assert "--network none" in joined
    assert "--read-only" in command
    assert "--cap-drop ALL" in joined
    assert "no-new-privileges" in command
    assert "--pids-limit 128" in joined
    assert "--user" in command
    assert "HOME=/tmp" in command
    assert "dst=/workspace" in joined
    assert str(workspace.resolve()) in joined


def test_run_command_line_starts_detached_session_container(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    sandbox = DockerSandbox(workspace=workspace, session_id="session-abc-123")
    command = sandbox.run_command_line()
    joined = " ".join(command)
    assert "--name harness-sbx-sessionabc123" in joined
    assert "-d" in command
    assert command[-2:] == ["sleep", "infinity"]


def test_command_line_uses_docker_exec(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    sandbox = DockerSandbox(workspace=workspace, session_id="session-abc-123")
    command = sandbox.command_line("python --version")
    assert command[:3] == ["docker", "exec", "harness-sbx-sessionabc123"]
    assert command[-3:] == ["sh", "-lc", "python --version"]


def test_nul_byte_is_rejected(tmp_path: Path) -> None:
    manager = SessionSandboxManager()
    with pytest.raises(ValueError, match="NUL"):
        manager.execute(
            "session-1",
            tmp_path,
            "langchain-harness-sandbox:latest",
            tmp_path,
            "echo \x00",
        )


@patch("agent_harness.sandbox.subprocess.run")
def test_output_is_limited(run: Mock, tmp_path: Path) -> None:
    manager = SessionSandboxManager()

    def side_effect(cmd, **kwargs):
        if cmd[1] == "info":
            return Mock(returncode=0, stdout="", stderr="")
        if cmd[1] == "image":
            return Mock(returncode=0, stdout="", stderr="")
        if cmd[1] == "inspect":
            return Mock(returncode=0, stdout="true", stderr="")
        if cmd[1] == "run":
            return Mock(returncode=0, stdout="ok", stderr="")
        if cmd[1] == "exec":
            return Mock(returncode=0, stdout="x" * 500, stderr="")
        return Mock(returncode=0, stdout="", stderr="")

    run.side_effect = side_effect
    output = manager.execute(
        "session-1",
        tmp_path,
        "langchain-harness-sandbox:latest",
        tmp_path,
        "echo ok",
        output_limit=100,
    )
    assert "OUTPUT TRONCATO" in output
    assert len(output) < 200


@patch("agent_harness.sandbox.subprocess.run")
def test_stop_removes_container(run: Mock, tmp_path: Path) -> None:
    manager = SessionSandboxManager()
    manager.stop("session-xyz")
    run.assert_called_once()
    assert run.call_args.args[0][:3] == ["docker", "rm", "-f"]
