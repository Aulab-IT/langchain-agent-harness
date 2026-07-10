from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent_harness.durable import (
    DurableStore,
    InvalidTransition,
    RunState,
    can_transition,
    idempotency_key,
    validate_transition,
)


def _store(tmp_path: Path) -> DurableStore:
    return DurableStore(tmp_path / "durable.sqlite")


def test_state_machine_rejects_terminal_reentry() -> None:
    assert can_transition(RunState.QUEUED, RunState.RUNNING)
    assert not can_transition(RunState.COMPLETED, RunState.RUNNING)
    with pytest.raises(InvalidTransition):
        validate_transition(RunState.COMPLETED, RunState.RUNNING)


def test_completed_and_incomplete_are_distinct() -> None:
    # Il mismatch "completed con completed=false" si elimina separando i due stati.
    assert RunState.COMPLETED != RunState.INCOMPLETE
    assert can_transition(RunState.RUNNING, RunState.INCOMPLETE)
    assert can_transition(RunState.RUNNING, RunState.COMPLETED)


def test_enqueue_is_idempotent(tmp_path: Path) -> None:
    store = _store(tmp_path)
    key = idempotency_key("session-1", "req-1")
    first = store.enqueue(kind="run", payload={"goal": "x"}, idempotency_key=key)
    second = store.enqueue(kind="run", payload={"goal": "x"}, idempotency_key=key)
    assert first.id == second.id  # nessun doppio inserimento
    store.close()


def test_claim_leases_and_second_worker_gets_nothing(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.enqueue(kind="run", payload={}, idempotency_key="k1")
    claimed = store.claim(owner="worker-a", lease_seconds=60)
    assert claimed is not None
    assert claimed.state == RunState.RUNNING
    assert claimed.attempts == 1
    # Un secondo worker non trova nulla di reclamabile: il lease è valido.
    assert store.claim(owner="worker-b", lease_seconds=60) is None
    store.close()


def test_expired_lease_is_reclaimed(tmp_path: Path) -> None:
    store = _store(tmp_path)
    past = datetime(2020, 1, 1, tzinfo=UTC)
    store.enqueue(kind="run", payload={}, idempotency_key="k1", now=past)
    store.claim(owner="dead-worker", lease_seconds=30, now=past)
    # Molto dopo la scadenza del lease: l'item torna reclamabile.
    reclaimed = store.reclaim_expired(now=past + timedelta(hours=1))
    assert len(reclaimed) == 1
    fresh = store.claim(owner="worker-b", lease_seconds=60, now=past + timedelta(hours=1))
    assert fresh is not None
    store.close()


def test_transition_optimistic_lock(tmp_path: Path) -> None:
    store = _store(tmp_path)
    item = store.enqueue(kind="run", payload={}, idempotency_key="k1")
    claimed = store.claim(owner="w", lease_seconds=60)
    assert claimed is not None
    # Transizione con versione sbagliata: rifiutata.
    with pytest.raises(InvalidTransition):
        store.transition(item.id, RunState.COMPLETED, expected_version=0)
    done = store.transition(claimed.id, RunState.COMPLETED, expected_version=claimed.version)
    assert done.state == RunState.COMPLETED
    assert done.lease_owner is None  # lease liberato allo stato terminale
    store.close()


def test_retry_backoff_then_dead_letter(tmp_path: Path) -> None:
    store = _store(tmp_path)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    store.enqueue(kind="run", payload={}, idempotency_key="k1", max_attempts=2, now=now)

    first = store.claim(owner="w", lease_seconds=60, now=now)
    assert first is not None
    scheduled = store.schedule_retry(
        first.id, expected_version=first.version, backoff_seconds=30, error="boom", now=now
    )
    assert scheduled.state == RunState.RETRY_SCHEDULED
    # Prima del backoff non è reclamabile; dopo, sì.
    assert store.claim(owner="w", lease_seconds=60, now=now) is None
    second = store.claim(owner="w", lease_seconds=60, now=now + timedelta(seconds=31))
    assert second is not None
    assert second.attempts == 2  # secondo tentativo
    # Esauriti i tentativi: dead-letter (FAILED).
    dead = store.schedule_retry(
        second.id,
        expected_version=second.version,
        backoff_seconds=30,
        error="boom again",
        now=now + timedelta(seconds=31),
    )
    assert dead.state == RunState.FAILED
    store.close()


def test_interrupt_persists_and_resolves_idempotently(tmp_path: Path) -> None:
    store = _store(tmp_path)
    interrupt = store.record_interrupt(
        run_id="run-1", kind="approval", payload={"command": "[redacted]"}
    )
    assert store.pending_interrupts("run-1")[0].id == interrupt.id
    resolved = store.resolve_interrupt(
        interrupt.id, resolution={"decision": "approve"}, resolved_by="user"
    )
    assert resolved.status == "resolved"
    assert resolved.resolution == {"decision": "approve"}
    # Seconda risoluzione: idempotente, non ricambia l'esito.
    again = store.resolve_interrupt(
        interrupt.id, resolution={"decision": "reject"}, resolved_by="attacker"
    )
    assert again.resolution == {"decision": "approve"}
    assert store.pending_interrupts("run-1") == []
    store.close()


def test_restart_survives_pending_approval(tmp_path: Path) -> None:
    # Simula il restart: nuovo DurableStore sullo stesso file ritrova l'interrupt pendente.
    path = tmp_path / "durable.sqlite"
    store = DurableStore(path)
    store.record_interrupt(run_id="run-1", kind="approval", payload={})
    store.close()

    reopened = DurableStore(path)
    pending = reopened.pending_interrupts("run-1")
    assert len(pending) == 1
    reopened.close()
