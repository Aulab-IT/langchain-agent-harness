from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import suppress
from pathlib import Path
from typing import Annotated, Any

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from pydantic import BaseModel, Field
from starlette.responses import Response

from agent_harness.config import Settings
from agent_harness.control_store import ControlStore
from agent_harness.factory import build_harness
from agent_harness.prompts import SYSTEM_PROMPT
from agent_harness.runner import GoalRunner
from agent_harness.sandbox import session_sandbox_manager

_LOGGER = logging.getLogger(__name__)
_TERMINAL_RUN_STATES = {"completed", "failed", "cancelled"}
_ALLOWED_UPLOADS = {
    ".csv",
    ".docx",
    ".gif",
    ".html",
    ".jpeg",
    ".jpg",
    ".json",
    ".md",
    ".pdf",
    ".png",
    ".pptx",
    ".py",
    ".sql",
    ".svg",
    ".tar",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".webp",
    ".xlsx",
    ".xml",
    ".yaml",
    ".yml",
    ".zip",
}
_MAX_UPLOAD_SIZE = 25 * 1024 * 1024
_ALLOWED_ORIGINS = {"http://127.0.0.1:5173", "http://localhost:5173"}

settings = Settings()
store = ControlStore(settings)


class SessionCreate(BaseModel):
    title: Annotated[str, Field(default="Nuova sessione", max_length=120)]


class SessionUpdate(BaseModel):
    title: Annotated[str, Field(min_length=1, max_length=120)]


class MessageCreate(BaseModel):
    content: Annotated[str, Field(min_length=1, max_length=20_000)]
    attachments: Annotated[list[str], Field(default_factory=list, max_length=50)]


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    output_tokens_per_second: float = 0
    context_categories: list[dict[str, Any]] = Field(default_factory=list)
    estimated_context: bool = True


def _token_estimate(value: Any) -> int:
    if isinstance(value, str):
        return max(0, round(len(value) / 4))
    return max(0, round(len(json.dumps(value, ensure_ascii=False)) / 4))


def _context_categories(messages: list[Any]) -> list[dict[str, Any]]:
    totals = {
        "System & memoria": _token_estimate(SYSTEM_PROMPT),
        "Conversazione": 0,
        "File letti": 0,
        "Skills": 0,
        "Tool output": 0,
    }
    tool_paths: dict[str, str] = {}
    for message in messages:
        if isinstance(message, AIMessage):
            totals["Conversazione"] += _token_estimate(message.text)
            for call in message.tool_calls:
                arguments = call.get("args", {})
                path = arguments.get("file_path") or arguments.get("path")
                if isinstance(path, str):
                    tool_paths[str(call.get("id", ""))] = path
        elif isinstance(message, HumanMessage):
            totals["Conversazione"] += _token_estimate(message.content)
        elif isinstance(message, SystemMessage):
            totals["System & memoria"] += _token_estimate(message.content)
        elif isinstance(message, ToolMessage):
            estimated = _token_estimate(message.content)
            path = tool_paths.get(message.tool_call_id, "")
            if path.startswith("/skills/"):
                totals["Skills"] += estimated
            elif path.startswith("/workspace/"):
                totals["File letti"] += estimated
            else:
                totals["Tool output"] += estimated
    denominator = max(sum(totals.values()), 1)
    colors = {
        "System & memoria": "#60a5fa",
        "Conversazione": "#8b5cf6",
        "File letti": "#34d399",
        "Skills": "#f472b6",
        "Tool output": "#f59e0b",
    }
    return [
        {
            "name": name,
            "tokens": tokens,
            "percent": round(tokens / denominator * 100),
            "color": colors[name],
        }
        for name, tokens in totals.items()
    ]


def _usage(messages: list[Any], elapsed_seconds: float) -> dict[str, Any]:
    input_tokens = 0
    output_tokens = 0
    for message in messages:
        if not isinstance(message, AIMessage) or not message.usage_metadata:
            continue
        input_tokens += int(message.usage_metadata.get("input_tokens", 0))
        output_tokens += int(message.usage_metadata.get("output_tokens", 0))
    return Usage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
        output_tokens_per_second=round(output_tokens / max(elapsed_seconds, 0.001), 1),
        context_categories=_context_categories(messages),
    ).model_dump()


def _sandbox_available() -> bool:
    return session_sandbox_manager.docker_available()


def _skills() -> list[dict[str, str]]:
    if not settings.skills_dir.exists():
        return []
    return [
        {"name": path.parent.name, "status": "ready"}
        for path in sorted(settings.skills_dir.glob("*/SKILL.md"))
    ]


def _tools() -> list[dict[str, str]]:
    names = ["current_utc_time", "docker_exec"]
    if settings.harness_enable_web_search:
        names.append("web_search")
    if settings.harness_enable_browser:
        names.append("browser_read")
    if settings.harness_enable_mcp:
        names.append("mcp:local_harness")
    return [{"name": name, "status": "ready"} for name in names]


def _require_session(session_id: str) -> dict[str, Any]:
    try:
        uuid.UUID(session_id)
        return store.get_session(session_id)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="Sessione non trovata.") from exc


def _require_run(run_id: str) -> dict[str, Any]:
    try:
        uuid.UUID(run_id)
        return store.get_run(run_id)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="Run non trovato.") from exc


def _safe_workspace_path(session_id: str, file_path: str) -> Path:
    workspace = store.workspace_dir(session_id).resolve()
    candidate = (workspace / file_path).resolve()
    if not candidate.is_relative_to(workspace) or candidate == workspace:
        raise HTTPException(status_code=400, detail="Percorso file non valido.")
    return candidate


def _format_size(size: int) -> str:
    if size >= 1_048_576:
        return f"{size / 1_048_576:.1f} MB"
    if size >= 1024:
        return f"{max(1, round(size / 1024))} KB"
    return f"{size} B"


def _attachment_manifest(session_id: str) -> str:
    """Elenco dei file presenti nel workspace, così l'agente li vede come allegati."""
    files = store.list_files(session_id)
    if not files:
        return ""
    lines = [
        f"- /workspace/{item['name']} ({item['type'] or 'FILE'}, {_format_size(int(item['size']))})"
        for item in files
    ]
    return (
        "\n\n[File allegati alla conversazione, già presenti nel workspace. "
        "Leggili con docker_exec prima di rispondere se sono rilevanti per l'obiettivo.]\n"
        + "\n".join(lines)
    )


def _extract_command(value: Any) -> str | None:
    if isinstance(value, dict):
        command = value.get("command")
        if isinstance(command, str):
            return command[:4_000]
        for nested in value.values():
            found = _extract_command(nested)
            if found:
                return found
    if isinstance(value, list):
        for nested in value:
            found = _extract_command(nested)
            if found:
                return found
    return None


class RunManager:
    def __init__(self) -> None:
        self.tasks: dict[str, asyncio.Task[None]] = {}
        self.approvals: dict[str, asyncio.Future[bool]] = {}
        self._lock = asyncio.Lock()

    def _emit(
        self,
        run_id: str,
        session_id: str,
        event_type: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        store.add_event(run_id, session_id, event_type, payload)

    async def start(
        self,
        session_id: str,
        content: str,
        attachments: list[str] | None = None,
    ) -> dict[str, Any]:
        async with self._lock:
            latest = store.latest_run(session_id)
            if latest and latest["status"] not in _TERMINAL_RUN_STATES:
                raise HTTPException(status_code=409, detail="Sessione già in esecuzione.")
            run = store.create_run(session_id)
            store.add_message(
                session_id, "user", content, run_id=run["id"], attachments=attachments
            )
            task = asyncio.create_task(
                self._execute(run["id"], session_id, content),
                name=f"harness-run-{run['id']}",
            )
            self.tasks[run["id"]] = task
            return run

    async def _execute(self, run_id: str, session_id: str, content: str) -> None:
        started = time.monotonic()
        loop = asyncio.get_running_loop()
        streamed_tokens = 0
        stream_started = time.monotonic()
        files_before = {item["name"]: item for item in store.list_files(session_id)}
        store.update_run(run_id, status="running")
        self._emit(run_id, session_id, "run.started", {"status": "running"})
        self._emit(run_id, session_id, "agent.started", {"model": settings.openai_model})

        def tool_event(event: dict[str, Any]) -> None:
            event_type = str(event.pop("type", "tool.updated"))
            loop.call_soon_threadsafe(self._emit, run_id, session_id, event_type, event)
            skill = event.get("skill")
            if isinstance(skill, str):
                skill_type = "skill.started" if event_type == "tool.started" else "skill.completed"
                loop.call_soon_threadsafe(
                    self._emit,
                    run_id,
                    session_id,
                    skill_type,
                    {"skill": skill},
                )

        def agent_event(event: dict[str, Any]) -> None:
            nonlocal streamed_tokens
            event_type = str(event.pop("type", "agent.updated"))
            if event_type == "assistant.delta":
                text = str(event.get("text", ""))
                streamed_tokens += max(1, round(len(text) / 4))
                elapsed = max(time.monotonic() - stream_started, 0.001)
                self._emit(run_id, session_id, event_type, {"text": text})
                self._emit(
                    run_id,
                    session_id,
                    "usage.live",
                    {
                        "output_tokens": streamed_tokens,
                        "output_tokens_per_second": round(streamed_tokens / elapsed, 1),
                        "estimated": True,
                    },
                )

        async def approval(payload: dict[str, Any]) -> bool:
            safe_payload = {
                "action": str(payload.get("action", "docker_exec")),
                "description": "Esecuzione comando in sandbox Docker isolata",
            }
            command = _extract_command(payload)
            if command:
                safe_payload["command"] = command
            future: asyncio.Future[bool] = loop.create_future()
            self.approvals[run_id] = future
            store.update_run(run_id, status="waiting_approval")
            self._emit(run_id, session_id, "approval.requested", safe_payload)
            try:
                approved = await asyncio.wait_for(future, timeout=600)
            except TimeoutError:
                approved = False
            finally:
                self.approvals.pop(run_id, None)
            store.update_run(run_id, status="running")
            self._emit(
                run_id,
                session_id,
                "approval.resolved",
                {"approved": approved},
            )
            return approved

        try:
            if not settings.openai_api_key:
                raise RuntimeError("OPENAI_API_KEY non configurata")
            root = store.prepare_session_root(session_id)
            async with build_harness(
                settings,
                session_id=session_id,
                workspace_dir=store.workspace_dir(session_id),
                backend_root=root,
                event_callback=tool_event,
            ) as harness:
                manifest = _attachment_manifest(session_id)
                goal = content + manifest if len(content) + len(manifest) <= 20_000 else content
                result = await GoalRunner(harness, approval, agent_event).run(
                    goal,
                    thread_id=session_id,
                )

            elapsed = time.monotonic() - started
            usage = _usage(result.messages, elapsed)
            clean_text = result.text.replace("[GOAL_COMPLETE]", "").strip()
            store.add_message(session_id, "assistant", clean_text, run_id=run_id)
            files_after = {item["name"]: item for item in store.list_files(session_id)}
            for name, metadata in files_after.items():
                if name not in files_before:
                    self._emit(run_id, session_id, "file.created", metadata)
                elif metadata["modified_at"] != files_before[name]["modified_at"]:
                    self._emit(run_id, session_id, "file.updated", metadata)
            store.update_run(run_id, status="completed", usage=usage)
            self._emit(run_id, session_id, "usage.updated", usage)
            self._emit(
                run_id,
                session_id,
                "assistant.completed",
                {"message": clean_text},
            )
            self._emit(
                run_id,
                session_id,
                "run.completed",
                {
                    "status": "completed",
                    "elapsed_ms": round(elapsed * 1_000),
                    "iterations": result.iterations,
                    "completed": result.completed,
                },
            )
        except asyncio.CancelledError:
            store.update_run(run_id, status="cancelled")
            self._emit(run_id, session_id, "run.cancelled", {"status": "cancelled"})
            raise
        except Exception:
            _LOGGER.exception("Agent run failed", extra={"run_id": run_id})
            store.update_run(
                run_id,
                status="failed",
                error="Esecuzione agente fallita. Controlla configurazione e log backend.",
            )
            self._emit(
                run_id,
                session_id,
                "run.failed",
                {"error": "Esecuzione agente fallita."},
            )
        finally:
            self.approvals.pop(run_id, None)
            self.tasks.pop(run_id, None)

    async def resolve_approval(self, run_id: str, approved: bool) -> None:
        _require_run(run_id)
        future = self.approvals.get(run_id)
        if future is None or future.done():
            raise HTTPException(status_code=409, detail="Nessuna approvazione pendente.")
        future.set_result(approved)

    async def cancel(self, run_id: str) -> None:
        run = _require_run(run_id)
        if run["status"] in _TERMINAL_RUN_STATES:
            raise HTTPException(status_code=409, detail="Run già terminato.")
        future = self.approvals.get(run_id)
        if future is not None and not future.done():
            future.set_result(False)
        task = self.tasks.get(run_id)
        if task is None:
            store.update_run(run_id, status="cancelled")
            self._emit(run_id, run["session_id"], "run.cancelled", {"status": "cancelled"})
            return
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


run_manager = RunManager()

app = FastAPI(title="Harness Control Center API", docs_url=None, redoc_url=None)
app.add_middleware(
    CORSMiddleware,
    allow_origins=sorted(_ALLOWED_ORIGINS),
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "Last-Event-ID"],
)


@app.middleware("http")
async def validate_origin(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    origin = request.headers.get("origin")
    if request.method in {"POST", "PATCH", "DELETE"} and origin and origin not in _ALLOWED_ORIGINS:
        return Response("Origin non consentita.", status_code=403)
    return await call_next(request)


@app.get("/api/status")
async def runtime_status() -> dict[str, Any]:
    return {
        "backend": "online",
        "configured": bool(settings.openai_api_key),
        "model": settings.openai_model,
        "strong_model": settings.openai_strong_model,
        "context_window": settings.harness_context_window,
        "skills": _skills(),
        "tools": _tools(),
        "sandbox": {
            "image": settings.harness_sandbox_image,
            "available": _sandbox_available(),
            "approval_required": settings.harness_require_approval,
            "network": "disabled",
            "memory": "512 MB",
            "cpu": "1 core",
        },
    }


@app.post("/api/sessions", status_code=status.HTTP_201_CREATED)
async def create_session(payload: SessionCreate) -> dict[str, Any]:
    return store.create_session(payload.title)


@app.get("/api/sessions")
async def list_sessions(
    search: Annotated[str, Query(max_length=200)] = "",
) -> list[dict[str, Any]]:
    return store.list_sessions(search)


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str) -> dict[str, Any]:
    session = _require_session(session_id)
    latest = store.latest_run(session_id)
    return {
        **session,
        "messages": store.list_messages(session_id),
        "files": store.list_files(session_id),
        "latest_run": latest,
        "events": store.list_events(latest["id"]) if latest else [],
        "trace_events": store.list_session_events(session_id),
        "sandbox": {
            **session_sandbox_manager.status(session_id),
            "image": settings.harness_sandbox_image,
        },
    }


@app.patch("/api/sessions/{session_id}")
async def update_session(session_id: str, payload: SessionUpdate) -> dict[str, Any]:
    _require_session(session_id)
    return store.rename_session(session_id, payload.title)


@app.delete("/api/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(session_id: str) -> None:
    _require_session(session_id)
    latest = store.latest_run(session_id)
    if latest and latest["status"] not in _TERMINAL_RUN_STATES:
        await run_manager.cancel(latest["id"])
    session_sandbox_manager.stop(session_id)
    store.delete_session(session_id)


@app.post("/api/sessions/{session_id}/messages", status_code=status.HTTP_202_ACCEPTED)
async def create_message(session_id: str, payload: MessageCreate) -> dict[str, Any]:
    _require_session(session_id)
    clean = payload.content.strip()
    if not clean:
        raise HTTPException(status_code=422, detail="Messaggio vuoto.")
    known = {item["name"] for item in store.list_files(session_id)}
    attachments = [Path(name).name for name in payload.attachments]
    attachments = [name for name in dict.fromkeys(attachments) if name in known]
    run = await run_manager.start(session_id, clean, attachments)
    return {"run_id": run["id"], "status": run["status"]}


@app.get("/api/sessions/{session_id}/events")
async def session_events(session_id: str) -> list[dict[str, Any]]:
    _require_session(session_id)
    return store.list_session_events(session_id)


@app.get("/api/runs/{run_id}")
async def get_run(run_id: str) -> dict[str, Any]:
    return _require_run(run_id)


@app.get("/api/runs/{run_id}/events")
async def stream_run_events(
    run_id: str,
    after: Annotated[int, Query(ge=0)] = 0,
) -> StreamingResponse:
    _require_run(run_id)

    async def stream() -> AsyncIterator[str]:
        cursor = after
        idle_ticks = 0
        while True:
            events = store.list_events(run_id, after_id=cursor)
            if events:
                idle_ticks = 0
                for event in events:
                    cursor = int(event["id"])
                    yield f"id: {cursor}\nevent: {event['type']}\ndata: {json.dumps(event)}\n\n"
            else:
                idle_ticks += 1
            run = store.get_run(run_id)
            if run["status"] in _TERMINAL_RUN_STATES and not events:
                break
            if idle_ticks >= 40:
                yield ": heartbeat\n\n"
                idle_ticks = 0
            await asyncio.sleep(0.25)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/runs/{run_id}/approve", status_code=status.HTTP_202_ACCEPTED)
async def approve_run(run_id: str) -> dict[str, str]:
    await run_manager.resolve_approval(run_id, True)
    return {"status": "approved"}


@app.post("/api/runs/{run_id}/reject", status_code=status.HTTP_202_ACCEPTED)
async def reject_run(run_id: str) -> dict[str, str]:
    await run_manager.resolve_approval(run_id, False)
    return {"status": "rejected"}


@app.post("/api/runs/{run_id}/cancel", status_code=status.HTTP_202_ACCEPTED)
async def cancel_run(run_id: str) -> dict[str, str]:
    await run_manager.cancel(run_id)
    return {"status": "cancelling"}


@app.post("/api/sessions/{session_id}/files", status_code=status.HTTP_201_CREATED)
async def upload_file(session_id: str, file: UploadFile) -> dict[str, Any]:
    _require_session(session_id)
    safe_name = Path(file.filename or "").name
    extension = Path(safe_name).suffix.lower()
    if not safe_name or extension not in _ALLOWED_UPLOADS:
        raise HTTPException(status_code=400, detail="Tipo file non supportato.")
    content = await file.read(_MAX_UPLOAD_SIZE + 1)
    await file.close()
    if len(content) > _MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=413, detail="File oltre limite 25 MB.")
    destination = _safe_workspace_path(session_id, safe_name)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)
    return {
        "name": safe_name,
        "size": len(content),
        "type": extension.lstrip(".").upper(),
    }


@app.get("/api/sessions/{session_id}/files/{file_path:path}")
async def download_file(session_id: str, file_path: str) -> FileResponse:
    _require_session(session_id)
    target = _safe_workspace_path(session_id, file_path)
    if not target.is_file() or target.is_symlink():
        raise HTTPException(status_code=404, detail="File non trovato.")
    return FileResponse(target, filename=target.name)


@app.delete(
    "/api/sessions/{session_id}/files/{file_path:path}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_file(session_id: str, file_path: str) -> None:
    _require_session(session_id)
    target = _safe_workspace_path(session_id, file_path)
    if not target.is_file() or target.is_symlink():
        raise HTTPException(status_code=404, detail="File non trovato.")
    target.unlink()


def main() -> None:
    uvicorn.run(
        "agent_harness.server:app",
        host="127.0.0.1",
        port=8000,
        reload=False,
        access_log=False,
    )


if __name__ == "__main__":
    main()
