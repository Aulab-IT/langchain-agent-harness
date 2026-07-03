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

