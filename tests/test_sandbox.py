from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from agent_harness.sandbox import (
    DockerSandbox,
    SandboxIdleReaper,
    SessionSandboxManager,
    cleanup_orphan_sandboxes,
)


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
    # run_flags NON deve includere l'immagine: dopo l'immagine, in `docker run`,
    # tutto è il comando eseguito nel container, non più opzioni docker.
    assert "langchain-harness-sandbox:latest" not in command


def test_run_command_line_starts_detached_session_container(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    sandbox = DockerSandbox(workspace=workspace, session_id="session-abc-123")
    command = sandbox.run_command_line()
    joined = " ".join(command)
    assert "--name harness-sbx-sessionabc123" in joined
    assert "-d" in command
    assert command[-2:] == ["sleep", "infinity"]
    # L'immagine deve stare DOPO --name/-d e PRIMA del comando ("sleep infinity"),
    # altrimenti "sleep infinity" viene interpretato come nome dell'immagine
    # e "--name ... -d" come comando da eseguire nel container (regressione reale).
    name_index = command.index("--name")
    image_index = command.index(sandbox.image)
    assert image_index > name_index
    assert command[image_index + 1 :] == ["sleep", "infinity"]


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


@patch.object(SessionSandboxManager, "is_running", return_value=False)
@patch.object(SessionSandboxManager, "ensure_image", return_value=None)
@patch.object(SessionSandboxManager, "docker_available", return_value=True)
@patch("agent_harness.sandbox.subprocess.run")
def test_ensure_running_places_image_before_command(
    run: Mock,
    _docker_available: Mock,
    _ensure_image: Mock,
    _is_running: Mock,
    tmp_path: Path,
) -> None:
    """Regressione: l'immagine deve precedere il comando ("sleep infinity"),
    altrimenti Docker esegue "--name ... -d sleep infinity" come comando nel
    container invece di avviarlo in background (container mai avviato)."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    run.side_effect = [
        Mock(returncode=0),  # docker rm -f
        Mock(returncode=0, stdout="", stderr=""),  # docker run
    ]
    manager = SessionSandboxManager()
    with patch.object(SessionSandboxManager, "is_running", side_effect=[False, True]):
        manager.ensure_running("session-1", workspace, "img:latest", tmp_path)
    run_command = run.call_args_list[1].args[0]
    assert run_command[-2:] == ["sleep", "infinity"]
    assert run_command[run_command.index("img:latest") + 1 :] == ["sleep", "infinity"]


def test_touch_and_idle_seconds_track_activity() -> None:
    manager = SessionSandboxManager()
    assert manager.idle_seconds("s-1") is None  # mai osservato

    manager.touch("s-1")
    idle = manager.idle_seconds("s-1")
    assert idle is not None
    assert idle < 1.0

    manager.forget("s-1")
    assert manager.idle_seconds("s-1") is None


@patch.object(SessionSandboxManager, "stop")
def test_reaper_stops_idle_unbusy_sessions_only(stop: Mock) -> None:
    manager = SessionSandboxManager()
    manager.touch("idle-session")
    manager.touch("busy-session")
    manager._last_used["idle-session"] = manager._last_used["idle-session"] - 3_600
    manager._last_used["busy-session"] = manager._last_used["busy-session"] - 3_600

    with patch.object(
        SessionSandboxManager,
        "list_container_names",
        return_value=["harness-sbx-idlesession", "harness-sbx-busysession"],
    ):
        reaper = SandboxIdleReaper(
            manager,
            lambda: ["idle-session", "busy-session", "fresh-session"],
            lambda session_id: session_id == "busy-session",
            idle_seconds=1_800,
        )
        stopped = reaper.sweep()

    assert stopped == ["idle-session"]
    stop.assert_called_once_with("idle-session")


@patch.object(SessionSandboxManager, "stop")
def test_reaper_ignores_sessions_below_threshold(stop: Mock) -> None:
    manager = SessionSandboxManager()
    manager.touch("recent-session")

    with patch.object(
        SessionSandboxManager, "list_container_names", return_value=["harness-sbx-recentsession"]
    ):
        reaper = SandboxIdleReaper(
            manager, lambda: ["recent-session"], lambda _sid: False, idle_seconds=1_800
        )
        stopped = reaper.sweep()

    assert stopped == []
    stop.assert_not_called()


@patch.object(SessionSandboxManager, "remove_container_by_name")
@patch.object(SessionSandboxManager, "list_container_names")
@patch.object(SessionSandboxManager, "docker_available", return_value=True)
def test_cleanup_orphan_sandboxes_removes_only_unknown_containers(
    _docker_available: Mock, list_names: Mock, remove: Mock
) -> None:
    manager = SessionSandboxManager()
    list_names.return_value = ["harness-sbx-known1234567890", "harness-sbx-ghost1234567890"]

    orphans = cleanup_orphan_sandboxes(manager, ["known1234567890"])

    assert orphans == ["harness-sbx-ghost1234567890"]
    remove.assert_called_once_with("harness-sbx-ghost1234567890")


@patch.object(SessionSandboxManager, "docker_available", return_value=False)
def test_cleanup_orphan_sandboxes_skips_when_docker_unavailable(_docker_available: Mock) -> None:
    manager = SessionSandboxManager()
    assert cleanup_orphan_sandboxes(manager, []) == []
