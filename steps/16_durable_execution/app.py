"""Step 16: coda durevole, lease, idempotenza e interrupt persistente."""

import tempfile
from pathlib import Path

from agent_harness.durable import DurableStore, RunState, idempotency_key


def main() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        database = Path(temporary) / "durable.sqlite"
        store = DurableStore(database)
        key = idempotency_key("session-1", "request-1")
        first = store.enqueue(kind="run", payload={"goal": "crea report"}, idempotency_key=key)
        duplicate = store.enqueue(kind="run", payload={"goal": "crea report"}, idempotency_key=key)
        assert first.id == duplicate.id
        claimed = store.claim(owner="worker-a", lease_seconds=30)
        assert claimed is not None
        interrupt = store.record_interrupt(
            run_id=claimed.id, kind="approval", payload={"command": "[redacted]"}
        )
        store.close()

        reopened = DurableStore(database)
        assert reopened.pending_interrupts(claimed.id)[0].id == interrupt.id
        reopened.resolve_interrupt(
            interrupt.id, resolution={"decision": "approve"}, resolved_by="student"
        )
        done = reopened.transition(
            claimed.id, RunState.COMPLETED, expected_version=claimed.version
        )
        print("Stesso item per retry:", first.id)
        print("Stato dopo restart:", done.state)
        reopened.close()


if __name__ == "__main__":
    main()
