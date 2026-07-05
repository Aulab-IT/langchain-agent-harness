import json
from pathlib import Path

from agent_harness.audit import AuditMiddleware


def test_audit_does_not_store_arguments_or_output(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    middleware = AuditMiddleware(path)
    middleware._write(tool="example", status="ok", elapsed_ms=12)
    event = json.loads(path.read_text(encoding="utf-8"))
    assert event["tool"] == "example"
    assert set(event) == {"timestamp", "tool", "status", "elapsed_ms"}


def test_audit_can_correlate_run_without_storing_payload(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    middleware = AuditMiddleware(path, run_id="run-1", session_id="session-1")

    middleware._write(tool="example", status="error", elapsed_ms=7)

    event = json.loads(path.read_text(encoding="utf-8"))
    assert event["run_id"] == "run-1"
    assert event["session_id"] == "session-1"
    assert set(event) == {
        "timestamp",
        "tool",
        "status",
        "elapsed_ms",
        "run_id",
        "session_id",
    }
