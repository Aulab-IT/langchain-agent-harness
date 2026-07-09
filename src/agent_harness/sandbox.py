from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field

from agent_harness.config import PROJECT_ROOT

_LOGGER = logging.getLogger(__name__)


class DockerExecInput(BaseModel):
    command: str = Field(
        min_length=1,
        max_length=4_000,
        description="Comando shell da eseguire dentro /workspace nel container isolato.",
    )
    timeout_seconds: int = Field(default=60, ge=1, le=120)


def _docker_ids() -> tuple[int, int]:
    return getattr(os, "getuid", lambda: 10001)(), getattr(os, "getgid", lambda: 10001)()


class SessionSandboxManager:
    """Un container Docker persistente per conversazione, avviato on-demand."""

    def __init__(self) -> None:
        self._locks: dict[str, threading.Lock] = {}
        self._registry_lock = threading.Lock()
        self._last_used: dict[str, float] = {}

    def container_name(self, session_id: str) -> str:
        safe = session_id.replace("-", "")[:20]
        return f"harness-sbx-{safe}"

    def _session_lock(self, session_id: str) -> threading.Lock:
        with self._registry_lock:
            return self._locks.setdefault(session_id, threading.Lock())

    def touch(self, session_id: str) -> None:
        """Segna un uso della sandbox della sessione (per il reaper di inattività)."""
        with self._registry_lock:
            self._last_used[session_id] = time.monotonic()

    def idle_seconds(self, session_id: str) -> float | None:
        """Secondi dall'ultimo uso, o None se non ancora osservato in questo processo."""
        with self._registry_lock:
            last = self._last_used.get(session_id)
        return None if last is None else time.monotonic() - last

    def forget(self, session_id: str) -> None:
        with self._registry_lock:
            self._last_used.pop(session_id, None)

    def list_container_names(self, *, only_running: bool = False) -> list[str]:
        """Nomi dei container harness-sbx-*; usato per sweep di inattività e orfani."""
        command = ["docker", "ps", "--format", "{{.Names}}", "--filter", "name=harness-sbx-"]
        if not only_running:
            command.append("-a")
        try:
            result = subprocess.run(
                command, capture_output=True, text=True, check=False, timeout=10
            )
        except (OSError, subprocess.TimeoutExpired):
            return []
        if result.returncode != 0:
            return []
        return [line for line in result.stdout.splitlines() if line.strip()]

    def remove_container_by_name(self, name: str) -> None:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, check=False, timeout=30)

    def docker_available(self) -> bool:
        if not shutil_which("docker"):
            return False
        try:
            result = subprocess.run(
                ["docker", "info"],
                capture_output=True,
                check=False,
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return result.returncode == 0

    def image_exists(self, image: str) -> bool:
        try:
            result = subprocess.run(
                ["docker", "image", "inspect", image],
                capture_output=True,
                check=False,
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return result.returncode == 0

    def ensure_image(self, image: str, project_root: Path) -> None:
        if self.image_exists(image):
            return
        dockerfile = project_root / "docker" / "sandbox.Dockerfile"
        if not dockerfile.is_file():
            raise RuntimeError(f"Dockerfile sandbox non trovato: {dockerfile}")
        result = subprocess.run(
            [
                "docker",
                "build",
                "-t",
                image,
                "-f",
                str(dockerfile),
                str(project_root),
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=900,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "errore sconosciuto").strip()
            raise RuntimeError(f"Build immagine sandbox fallita:\n{detail}")

    def is_running(self, session_id: str) -> bool:
        name = self.container_name(session_id)
        try:
            result = subprocess.run(
                ["docker", "inspect", "-f", "{{.State.Running}}", name],
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return result.returncode == 0 and result.stdout.strip() == "true"

    def status(self, session_id: str) -> dict[str, str | bool | None]:
        if not self.docker_available():
            return {"state": "unavailable", "container": None, "running": False}
        name = self.container_name(session_id)
        running = self.is_running(session_id)
        return {
            "state": "running" if running else "idle",
            "container": name if running else None,
            "running": running,
        }

    def run_flags(self, workspace: Path, image: str, skills_dir: Path | None = None) -> list[str]:
        """Flag di sicurezza per `docker run`, SENZA l'immagine.

        In `docker run [OPTIONS] IMAGE [COMMAND]` tutto ciò che segue l'immagine è il
        comando eseguito nel container, non un'opzione docker. L'immagine va quindi
        aggiunta dal chiamante subito prima del comando (es. `--name` deve stare tra
        queste opzioni e l'immagine, mai dopo).

        Se `skills_dir` esiste, viene montata read-only su /skills così l'agente può
        eseguirne gli script (senza poterli modificare dal container).
        """
        if "\x00" in image:
            raise ValueError("Nome immagine non valido.")
        workspace = workspace.resolve()
        user_id, group_id = _docker_ids()
        flags = [
            "docker",
            "run",
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--memory",
            "512m",
            "--cpus",
            "1",
            "--pids-limit",
            "128",
            "--user",
            f"{user_id}:{group_id}",
            "--env",
            "HOME=/tmp",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=64m",
            "--mount",
            f"type=bind,src={workspace},dst=/workspace",
        ]
        if skills_dir is not None and skills_dir.exists():
            flags += [
                "--mount",
                f"type=bind,src={skills_dir.resolve()},dst=/skills,readonly",
            ]
        flags += [
            "--workdir",
            "/workspace",
        ]
        return flags

    def ensure_running(
        self,
        session_id: str,
        workspace: Path,
        image: str,
        project_root: Path,
    ) -> str:
        with self._session_lock(session_id):
            if not self.docker_available():
                raise RuntimeError("Docker non è installato o il demone non è attivo.")
            self.ensure_image(image, project_root)
            name = self.container_name(session_id)
            if self.is_running(session_id):
                return name
            subprocess.run(
                ["docker", "rm", "-f", name],
                capture_output=True,
                check=False,
                timeout=15,
            )
            command = [
                *self.run_flags(workspace, image, project_root / "skills"),
                "--name",
                name,
                "-d",
                image,
                "sleep",
                "infinity",
            ]
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )
            if result.returncode != 0:
                detail = (result.stderr or result.stdout or "avvio fallito").strip()
                raise RuntimeError(f"Avvio sandbox sessione fallito:\n{detail}")
            if not self.is_running(session_id):
                raise RuntimeError("Container sandbox non risulta in esecuzione dopo l'avvio.")
            return name

    def stop(self, session_id: str) -> None:
        with self._session_lock(session_id):
            name = self.container_name(session_id)
            subprocess.run(
                ["docker", "rm", "-f", name],
                capture_output=True,
                check=False,
                timeout=30,
            )
        self.forget(session_id)

    def execute(
        self,
        session_id: str,
        workspace: Path,
        image: str,
        project_root: Path,
        command: str,
        *,
        timeout_seconds: int = 60,
        output_limit: int = 12_000,
    ) -> str:
        if "\x00" in command:
            raise ValueError("Il comando contiene un byte NUL.")
        self.touch(session_id)
        try:
            container = self.ensure_running(session_id, workspace, image, project_root)
            result = subprocess.run(
                ["docker", "exec", container, "sh", "-lc", command],
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
        except FileNotFoundError:
            return "ERRORE: Docker non è installato o non è nel PATH."
        except subprocess.TimeoutExpired:
            return f"ERRORE: comando interrotto dopo {timeout_seconds} secondi."
        except RuntimeError as exc:
            return f"ERRORE: {exc}"

        combined = (
            f"exit_code={result.returncode}\n"
            f"STDOUT:\n{result.stdout}\n"
            f"STDERR:\n{result.stderr}"
        )
        if len(combined) <= output_limit:
            return combined
        head = combined[: output_limit // 2]
        tail = combined[-output_limit // 2 :]
        return f"{head}\n\n... OUTPUT TRONCATO ...\n\n{tail}"


def shutil_which(cmd: str) -> str | None:
    import shutil

    return shutil.which(cmd)


session_sandbox_manager = SessionSandboxManager()


def cleanup_orphan_sandboxes(
    manager: SessionSandboxManager, known_session_ids: list[str]
) -> list[str]:
    """Rimuove i container harness-sbx-* la cui sessione non esiste più nel DB.

    Copre i residui lasciati da sessioni cancellate mentre il container era attivo
    (es. crash) o da bug passati. Va chiamata all'avvio del backend.
    """
    if not manager.docker_available():
        return []
    known_names = {manager.container_name(session_id) for session_id in known_session_ids}
    orphans = [name for name in manager.list_container_names() if name not in known_names]
    for name in orphans:
        manager.remove_container_by_name(name)
    return orphans


class SandboxIdleReaper:
    """Ferma i container sandbox inattivi da troppo tempo, per liberare risorse.

    L'inattività è tracciata in memoria da `SessionSandboxManager.touch()`, quindi
    riguarda l'uso avvenuto nel processo backend corrente: dopo un riavvio il timer
    riparte da zero per i container già in esecuzione (nessuno spegnimento improvviso
    di un container che magari sta per essere riusato).
    """

    def __init__(
        self,
        manager: SessionSandboxManager,
        list_known_session_ids: Callable[[], list[str]],
        is_session_busy: Callable[[str], bool],
        *,
        idle_seconds: float,
        tick_seconds: float = 60,
    ) -> None:
        self.manager = manager
        self.list_known_session_ids = list_known_session_ids
        self.is_session_busy = is_session_busy
        self.idle_seconds = idle_seconds
        self.tick_seconds = tick_seconds
        self._task: asyncio.Task[None] | None = None

    def sweep(self) -> list[str]:
        """Valuta una volta i container attivi e ferma quelli inattivi. Ritorna gli id fermati."""
        running_names = set(self.manager.list_container_names(only_running=True))
        if not running_names:
            return []
        stopped: list[str] = []
        for session_id in self.list_known_session_ids():
            if self.manager.container_name(session_id) not in running_names:
                continue
            if self.is_session_busy(session_id):
                continue
            idle = self.manager.idle_seconds(session_id)
            if idle is not None and idle >= self.idle_seconds:
                self.manager.stop(session_id)
                stopped.append(session_id)
        return stopped

    async def _loop(self) -> None:
        while True:
            try:
                self.sweep()
            except Exception:
                _LOGGER.exception("Sweep di inattività sandbox fallito")
            await asyncio.sleep(self.tick_seconds)

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop(), name="sandbox-idle-reaper")

    async def stop_task(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None


@dataclass(frozen=True)
class DockerSandbox:
    """Esegue comandi nel container persistente della conversazione."""

    workspace: Path
    session_id: str
    image: str = "langchain-harness-sandbox:latest"
    output_limit: int = 12_000
    project_root: Path = PROJECT_ROOT
    manager: SessionSandboxManager = field(default_factory=lambda: session_sandbox_manager)

    def command_line(self, command: str) -> list[str]:
        """Compatibilità test: flags del container di sessione + comando exec."""
        if "\x00" in command:
            raise ValueError("Il comando contiene un byte NUL.")
        container = self.manager.container_name(self.session_id)
        return ["docker", "exec", container, "sh", "-lc", command]

    def run_command_line(self, command: str = "sleep infinity") -> list[str]:
        """Compatibilità test: comando docker run per avviare il container."""
        flags = self.manager.run_flags(self.workspace, self.image)
        return [
            *flags,
            "--name",
            self.manager.container_name(self.session_id),
            "-d",
            self.image,
            *command.split(),
        ]

    def execute(self, command: str, timeout_seconds: int = 60) -> str:
        return self.manager.execute(
            self.session_id,
            self.workspace,
            self.image,
            self.project_root,
            command,
            timeout_seconds=timeout_seconds,
            output_limit=self.output_limit,
        )

    def as_tool(self) -> BaseTool:
        return StructuredTool.from_function(
            func=self.execute,
            name="docker_exec",
            description=(
                "Esegue test, script e comandi in un container Docker isolato dedicato "
                "a questa conversazione. La sandbox viene avviata automaticamente al primo "
                "uso. Solo /workspace è condiviso in scrittura."
            ),
            args_schema=DockerExecInput,
        )
