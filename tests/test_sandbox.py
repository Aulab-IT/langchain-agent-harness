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
    command = manager.run_flags(
        workspace, "langchain-harness-sandbox:latest", isolated_network="harness-net-abc"
    )
    joined = " ".join(command)
    # La rete di base è la rete `--internal` dedicata alla sessione (NON `none`),
    # così è possibile collegare a caldo internet per gli install su conferma.
    assert "--network harness-net-abc" in joined
    assert "--network none" not in joined
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
    # Output oltre il limite: l'integrale finisce su file, nel contesto entra un estratto
    # compatto più il riferimento recuperabile (non più un troncamento con perdita).
    assert "[tool-output-offloaded]" in output
    assert "/workspace/.tool_output/" in output
    assert len(output) < 700
    saved = list((tmp_path / ".tool_output").glob("*.txt"))
    assert len(saved) == 1 and saved[0].stat().st_size > 100


@patch("agent_harness.sandbox.subprocess.run")
def test_output_offload_falls_back_to_truncation_when_unwritable(
    run: Mock, tmp_path: Path
) -> None:
    manager = SessionSandboxManager()

    def side_effect(cmd, **kwargs):
        if cmd[1] == "exec":
            return Mock(returncode=0, stdout="x" * 500, stderr="")
        return Mock(returncode=0, stdout="true" if cmd[1] == "inspect" else "", stderr="")

    run.side_effect = side_effect
    # Workspace inesistente e non creabile (un file al posto della cartella): l'offload fallisce
    # e si ricade sul troncamento, così l'output non va perso del tutto.
    blocked = tmp_path / "afile"
    blocked.write_text("x")
    output = manager.execute(
        "session-2",
        blocked / "ws",
        "langchain-harness-sandbox:latest",
        tmp_path,
        "echo ok",
        output_limit=100,
    )
    assert "OUTPUT TRONCATO" in output


def _exec_stub(exec_result: Mock | None = None):
    """side_effect per subprocess.run che simula un container già in esecuzione."""

    def side_effect(cmd, **kwargs):
        verb = cmd[1]
        if verb == "info":
            return Mock(returncode=0, stdout="", stderr="")
        if verb == "image":
            return Mock(returncode=0, stdout="", stderr="")
        if verb == "inspect":
            # container_networks() usa un template su .NetworkSettings.Networks: risponde
            # con la rete isolata attesa così il container "running" viene riusato.
            fmt = cmd[3] if len(cmd) > 3 else ""
            if "Networks" in fmt:
                return Mock(returncode=0, stdout="harness-net-session1", stderr="")
            return Mock(returncode=0, stdout="true", stderr="")
        if verb == "exec":
            if exec_result is not None:
                return exec_result
            return Mock(returncode=0, stdout="ok", stderr="")
        return Mock(returncode=0, stdout="", stderr="")

    return side_effect


@patch("agent_harness.sandbox.subprocess.run")
def test_execute_with_network_connects_then_disconnects(run: Mock, tmp_path: Path) -> None:
    run.side_effect = _exec_stub()
    manager = SessionSandboxManager()
    manager.execute(
        "session-1",
        tmp_path,
        "img:latest",
        tmp_path,
        "pip install --target /workspace/.pylib rich",
        with_network=True,
        network="bridge",
    )
    verbs = [
        (call.args[0][1], call.args[0][2] if len(call.args[0]) > 2 else "")
        for call in run.call_args_list
    ]
    # connect prima dell'exec, disconnect dopo.
    connect_idx = verbs.index(("network", "connect"))
    exec_idx = next(i for i, v in enumerate(verbs) if v[0] == "exec")
    disconnect_idx = verbs.index(("network", "disconnect"))
    assert connect_idx < exec_idx < disconnect_idx


@patch("agent_harness.sandbox.subprocess.run")
def test_execute_with_network_disconnects_even_on_exec_failure(
    run: Mock, tmp_path: Path
) -> None:
    import subprocess

    def side_effect(cmd, **kwargs):
        if cmd[1] == "exec":
            raise subprocess.TimeoutExpired(cmd, 1)
        return _exec_stub()(cmd, **kwargs)

    run.side_effect = side_effect
    manager = SessionSandboxManager()
    output = manager.execute(
        "session-1",
        tmp_path,
        "img:latest",
        tmp_path,
        "sleep 999",
        with_network=True,
        timeout_seconds=1,
    )
    assert "interrotto" in output
    verbs = [
        (call.args[0][1], call.args[0][2] if len(call.args[0]) > 2 else "")
        for call in run.call_args_list
    ]
    # Il finally deve aver revocato la rete anche col comando fallito.
    assert ("network", "disconnect") in verbs


@patch("agent_harness.sandbox.subprocess.run")
def test_execute_without_network_never_touches_network(run: Mock, tmp_path: Path) -> None:
    run.side_effect = _exec_stub()
    manager = SessionSandboxManager()
    manager.execute("session-1", tmp_path, "img:latest", tmp_path, "echo ok")
    verbs = [call.args[0][1] for call in run.call_args_list]
    assert "network" not in verbs


@patch("agent_harness.sandbox.subprocess.run")
def test_stop_removes_container_and_network(run: Mock, tmp_path: Path) -> None:
    run.return_value = Mock(returncode=0, stdout="", stderr="")
    manager = SessionSandboxManager()
    manager.stop("session-xyz")
    calls = [call.args[0] for call in run.call_args_list]
    assert ["docker", "rm", "-f", "harness-sbx-sessionxyz"] in calls
    assert ["docker", "network", "rm", "harness-net-sessionxyz"] in calls


@patch.object(SessionSandboxManager, "is_running", side_effect=[False, True])
@patch.object(SessionSandboxManager, "ensure_image", return_value=None)
@patch.object(SessionSandboxManager, "docker_available", return_value=True)
@patch("agent_harness.sandbox.subprocess.run")
def test_ensure_running_creates_isolated_network_and_uses_it(
    run: Mock,
    _docker_available: Mock,
    _ensure_image: Mock,
    _is_running: Mock,
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    def side_effect(cmd, **kwargs):
        # La rete non esiste ancora → inspect fallisce, così ensure_network la crea.
        if cmd[1] == "network" and cmd[2] == "inspect":
            return Mock(returncode=1, stdout="", stderr="")
        return Mock(returncode=0, stdout="", stderr="")

    run.side_effect = side_effect
    manager = SessionSandboxManager()
    manager.ensure_running("session-1", workspace, "img:latest", tmp_path)
    calls = [call.args[0] for call in run.call_args_list]
    net = "harness-net-session1"
    assert ["docker", "network", "create", "--internal", "--driver", "bridge", net] in calls
    run_cmd = next(c for c in calls if c[:2] == ["docker", "run"])
    joined = " ".join(run_cmd)
    assert f"--network {net}" in joined
    assert "--network none" not in joined


@patch.object(SessionSandboxManager, "container_networks", return_value={"none"})
@patch.object(SessionSandboxManager, "is_running", return_value=True)
@patch.object(SessionSandboxManager, "ensure_image", return_value=None)
@patch.object(SessionSandboxManager, "docker_available", return_value=True)
@patch("agent_harness.sandbox.subprocess.run")
def test_ensure_running_recreates_container_on_wrong_network(
    run: Mock,
    _docker_available: Mock,
    _ensure_image: Mock,
    _is_running: Mock,
    _networks: Mock,
    tmp_path: Path,
) -> None:
    """Migrazione: un container avviato da una versione precedente (rete `none`) non è
    collegabile a internet, quindi va ricreato invece di riusarlo."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    run.return_value = Mock(returncode=0, stdout="", stderr="")
    manager = SessionSandboxManager()
    manager.ensure_running("session-1", workspace, "img:latest", tmp_path)
    calls = [call.args[0] for call in run.call_args_list]
    # Nonostante il container sia "running", NON viene riusato: prima rm -f, poi run.
    assert ["docker", "rm", "-f", "harness-sbx-session1"] in calls
    assert any(c[:2] == ["docker", "run"] for c in calls)


@patch.object(SessionSandboxManager, "remove_network")
@patch.object(SessionSandboxManager, "remove_container_by_name")
@patch.object(SessionSandboxManager, "list_network_names")
@patch.object(SessionSandboxManager, "list_container_names", return_value=[])
@patch.object(SessionSandboxManager, "docker_available", return_value=True)
def test_cleanup_removes_orphan_networks(
    _avail: Mock,
    _containers: Mock,
    list_networks: Mock,
    _remove_container: Mock,
    remove_network: Mock,
) -> None:
    list_networks.return_value = ["harness-net-known1234567890", "harness-net-ghost1234567890"]
    cleanup_orphan_sandboxes(SessionSandboxManager(), ["known1234567890"])
    remove_network.assert_called_once_with("harness-net-ghost1234567890")


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
    run.return_value = Mock(returncode=0, stdout="", stderr="")
    manager = SessionSandboxManager()
    with patch.object(SessionSandboxManager, "is_running", side_effect=[False, True]):
        manager.ensure_running("session-1", workspace, "img:latest", tmp_path)
    calls = [call.args[0] for call in run.call_args_list]
    run_command = next(c for c in calls if c[:2] == ["docker", "run"])
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
