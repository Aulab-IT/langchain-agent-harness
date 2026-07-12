"""Lavoro durevole: state machine di run, coda con lease, interrupt persistenti (Fase 3).

Oggi run, approvazioni e user action vivono in memoria: un restart del backend marca i run
come falliti e perde gli interrupt pendenti. Qui lo stato diventa durevole e ``asyncio.Task``
torna a essere un dettaglio esecutivo, non la fonte di verità.

Prima iterazione su SQLite (il piano, §7.3, la prevede esplicitamente): claim atomico con
lease, heartbeat, retry con backoff, dead-letter. Quando servirà multi-host, un adattatore
Postgres/Redis sostituisce lo storage senza toccare l'application service.

Due garanzie centrali:

- **transizioni validate con optimistic locking**: ogni scrittura dichiara la versione che
  si aspetta; se un altro worker ha già cambiato l'item, la transizione viene rifiutata;
- **idempotency key su ogni side effect**: creare un run, far scattare un trigger o
  rispondere a un'approvazione due volte non produce due esecuzioni.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any


class RunState(StrEnum):
    """Stati durevoli di un'unità di lavoro.

    ``COMPLETED`` e ``INCOMPLETE`` sono distinti di proposito: oggi un run tecnicamente
    terminato può avere status ``completed`` ma payload ``completed=false``. Separarli
    elimina quel mismatch (§7.2 del piano).
    """

    QUEUED = "queued"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    WAITING_USER_ACTION = "waiting_user_action"
    RETRY_SCHEDULED = "retry_scheduled"
    COMPLETED = "completed"
    INCOMPLETE = "incomplete"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_STATES: frozenset[RunState] = frozenset(
    {RunState.COMPLETED, RunState.INCOMPLETE, RunState.FAILED, RunState.CANCELLED}
)

# Transizioni ammesse. Fuori da questa mappa la transizione è rifiutata: uno stato terminale
# non torna indietro, e non si salta da queued a completed senza passare per running.
VALID_TRANSITIONS: dict[RunState, frozenset[RunState]] = {
    RunState.QUEUED: frozenset({RunState.RUNNING, RunState.CANCELLED}),
    RunState.RUNNING: frozenset(
        {
            RunState.WAITING_APPROVAL,
            RunState.WAITING_USER_ACTION,
            RunState.RETRY_SCHEDULED,
            RunState.COMPLETED,
            RunState.INCOMPLETE,
            RunState.FAILED,
            RunState.CANCELLED,
        }
    ),
    RunState.WAITING_APPROVAL: frozenset(
        {RunState.RUNNING, RunState.CANCELLED, RunState.FAILED}
    ),
    RunState.WAITING_USER_ACTION: frozenset(
        {RunState.RUNNING, RunState.CANCELLED, RunState.FAILED}
    ),
    RunState.RETRY_SCHEDULED: frozenset({RunState.RUNNING, RunState.CANCELLED, RunState.FAILED}),
    RunState.COMPLETED: frozenset(),
    RunState.INCOMPLETE: frozenset(),
    RunState.FAILED: frozenset(),
    RunState.CANCELLED: frozenset(),
}


class InvalidTransition(Exception):
    """Sollevata quando si tenta una transizione non ammessa o su una versione superata."""


def can_transition(current: RunState, target: RunState) -> bool:
    return target in VALID_TRANSITIONS.get(current, frozenset())


def validate_transition(current: RunState, target: RunState) -> None:
    if not can_transition(current, target):
        raise InvalidTransition(f"{current.value} → {target.value} non ammessa")


def idempotency_key(*parts: str | int) -> str:
    """Chiave stabile da componenti: stesse parti → stessa chiave, side effect una volta sola."""
    return "|".join(str(part) for part in parts)


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(moment: datetime) -> str:
    return moment.isoformat()


@dataclass(frozen=True)
class WorkItem:
    """Riga della coda, con stato durevole e versione per l'optimistic locking."""

    id: str
    kind: str
    state: RunState
    version: int
    payload: dict[str, Any]
    run_id: str | None
    session_id: str | None
    idempotency_key: str
    attempts: int
    max_attempts: int
    available_at: str
    lease_owner: str | None
    lease_expires_at: str | None
    last_error: str | None


@dataclass(frozen=True)
class Interrupt:
    """Approvazione o user action persistita: sopravvive al restart e si può risolvere dopo."""

    id: str
    run_id: str
    work_item_id: str | None
    kind: str
    payload: dict[str, Any]
    status: str
    created_at: str
    expires_at: str | None
    resolved_at: str | None
    resolution: dict[str, Any] | None
    resolved_by: str | None


class DurableStore:
    """Coda di lavoro e interrupt persistiti su SQLite.

    Prende un percorso file proprio (o ``:memory:`` nei test): è autonomo dal control DB,
    così lo si può testare in isolamento e, più avanti, sostituire con un backend distribuito.
    """

    def __init__(self, path: Path | str) -> None:
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(str(path), check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._connection.execute("PRAGMA busy_timeout = 5000")
        self._setup()

    def _setup(self) -> None:
        with self._lock, self._connection:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS work_items (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    state TEXT NOT NULL,
                    version INTEGER NOT NULL DEFAULT 0,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    run_id TEXT,
                    session_id TEXT,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL DEFAULT 3,
                    available_at TEXT NOT NULL,
                    lease_owner TEXT,
                    lease_expires_at TEXT,
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS interrupts (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    work_item_id TEXT,
                    kind TEXT NOT NULL,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL DEFAULT 'pending',
                    idempotency_key TEXT UNIQUE,
                    created_at TEXT NOT NULL,
                    expires_at TEXT,
                    resolved_at TEXT,
                    resolution_json TEXT,
                    resolved_by TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_work_items_claimable
                    ON work_items(state, available_at);
                CREATE INDEX IF NOT EXISTS idx_interrupts_run
                    ON interrupts(run_id, status);
                """
            )

    # ---- coda di lavoro ------------------------------------------------------

    def enqueue(
        self,
        *,
        kind: str,
        payload: dict[str, Any],
        idempotency_key: str,
        run_id: str | None = None,
        session_id: str | None = None,
        max_attempts: int = 3,
        now: datetime | None = None,
    ) -> WorkItem:
        """Accoda un'unità di lavoro. Idempotente sulla chiave: se già presente, la restituisce
        invece di crearne una seconda — è la garanzia contro il doppio inserimento."""
        stamp = _iso(now or _now())
        item_id = str(uuid.uuid4())
        with self._lock, self._connection:
            existing = self._connection.execute(
                "SELECT id FROM work_items WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            if existing is not None:
                return self._require(existing["id"])
            self._connection.execute(
                """
                INSERT INTO work_items(
                    id, kind, state, version, payload_json, run_id, session_id,
                    idempotency_key, attempts, max_attempts, available_at,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, 0, ?, ?, ?, ?, 0, ?, ?, ?, ?)
                """,
                (
                    item_id,
                    kind,
                    RunState.QUEUED.value,
                    json.dumps(payload, ensure_ascii=False),
                    run_id,
                    session_id,
                    idempotency_key,
                    max_attempts,
                    stamp,
                    stamp,
                    stamp,
                ),
            )
        return self._require(item_id)

    def claim_once(
        self,
        key: str,
        *,
        kind: str = "fire",
        payload: dict[str, Any] | None = None,
        run_id: str | None = None,
        session_id: str | None = None,
        now: datetime | None = None,
    ) -> bool:
        """Reclama una chiave una sola volta, in modo durevole e atomico.

        Restituisce ``True`` se la chiave è nuova (il chiamante procede col side effect),
        ``False`` se era già stata reclamata — anche in un'esecuzione precedente del backend.
        È la garanzia «una volta sola» che sopravvive al riavvio: due tick nello stesso minuto,
        o un riavvio dentro quel minuto, non fanno scattare due volte lo stesso trigger.

        Il controllo e l'inserimento avvengono sotto lo stesso lock, quindi non c'è finestra fra
        «esiste?» e «inserisci» in cui due chiamate possano entrambe vedere la chiave assente.
        """
        stamp = _iso(now or _now())
        with self._lock, self._connection:
            existing = self._connection.execute(
                "SELECT 1 FROM work_items WHERE idempotency_key = ?", (key,)
            ).fetchone()
            if existing is not None:
                return False
            self._connection.execute(
                """
                INSERT INTO work_items(
                    id, kind, state, version, payload_json, run_id, session_id,
                    idempotency_key, attempts, max_attempts, available_at,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, 0, ?, ?, ?, ?, 0, 0, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    kind,
                    # Marcatore già consumato: uno stato terminale non viene mai reclamato.
                    RunState.COMPLETED.value,
                    json.dumps(payload or {}, ensure_ascii=False),
                    run_id,
                    session_id,
                    key,
                    stamp,
                    stamp,
                    stamp,
                ),
            )
        return True

    def claim(
        self, *, owner: str, lease_seconds: int = 60, now: datetime | None = None
    ) -> WorkItem | None:
        """Reclama la prossima unità disponibile con un lease atomico.

        Sceglie un item in coda (o pronto per retry) il cui ``available_at`` è passato e senza
        lease valido, lo porta in ``running`` con proprietario e scadenza lease, e incrementa
        gli attempts. Il ``WHERE version = ?`` rende il claim sicuro contro un secondo worker.
        """
        moment = now or _now()
        stamp = _iso(moment)
        expires = _iso(moment + timedelta(seconds=lease_seconds))
        with self._lock, self._connection:
            row = self._connection.execute(
                """
                SELECT * FROM work_items
                WHERE state IN ('queued', 'retry_scheduled')
                  AND available_at <= ?
                  AND (lease_expires_at IS NULL OR lease_expires_at <= ?)
                ORDER BY available_at, created_at
                LIMIT 1
                """,
                (stamp, stamp),
            ).fetchone()
            if row is None:
                return None
            updated = self._connection.execute(
                """
                UPDATE work_items
                SET state = 'running', version = version + 1, attempts = attempts + 1,
                    lease_owner = ?, lease_expires_at = ?, updated_at = ?
                WHERE id = ? AND version = ?
                """,
                (owner, expires, stamp, row["id"], row["version"]),
            )
            if updated.rowcount == 0:
                # Un altro worker ha vinto la corsa fra la SELECT e l'UPDATE.
                return None
        return self._require(row["id"])

    def heartbeat(
        self, item_id: str, *, owner: str, lease_seconds: int = 60, now: datetime | None = None
    ) -> bool:
        """Estende il lease di un item in esecuzione. Falso se l'item non è più di questo owner."""
        moment = now or _now()
        expires = _iso(moment + timedelta(seconds=lease_seconds))
        with self._lock, self._connection:
            updated = self._connection.execute(
                """
                UPDATE work_items
                SET lease_expires_at = ?, updated_at = ?
                WHERE id = ? AND lease_owner = ? AND state = 'running'
                """,
                (expires, _iso(moment), item_id, owner),
            )
        return updated.rowcount > 0

    def transition(
        self,
        item_id: str,
        target: RunState,
        *,
        expected_version: int,
        error: str | None = None,
    ) -> WorkItem:
        """Applica una transizione validata con optimistic locking.

        Rifiuta la transizione se non ammessa dalla state machine o se la versione attesa non
        combacia (qualcun altro ha già modificato l'item).
        """
        with self._lock, self._connection:
            item = self._require(item_id)
            if item.version != expected_version:
                raise InvalidTransition(
                    f"versione attesa {expected_version}, trovata {item.version}"
                )
            validate_transition(item.state, target)
            clear_lease = target in TERMINAL_STATES
            self._connection.execute(
                """
                UPDATE work_items
                SET state = ?, version = version + 1, last_error = ?, updated_at = ?,
                    lease_owner = CASE WHEN ? THEN NULL ELSE lease_owner END,
                    lease_expires_at = CASE WHEN ? THEN NULL ELSE lease_expires_at END
                WHERE id = ? AND version = ?
                """,
                (
                    target.value,
                    error,
                    _iso(_now()),
                    clear_lease,
                    clear_lease,
                    item_id,
                    expected_version,
                ),
            )
        return self._require(item_id)

    def schedule_retry(
        self,
        item_id: str,
        *,
        expected_version: int,
        backoff_seconds: int,
        error: str,
        now: datetime | None = None,
    ) -> WorkItem:
        """Programma un retry con backoff, o manda in dead-letter (``FAILED``) se esauriti.

        Il retry riporta l'item in coda con ``available_at`` nel futuro; superato
        ``max_attempts`` diventa ``FAILED`` e non viene più reclamato.
        """
        moment = now or _now()
        item = self._require(item_id)
        if item.attempts >= item.max_attempts:
            return self.transition(
                item_id, RunState.FAILED, expected_version=expected_version, error=error
            )
        available = _iso(moment + timedelta(seconds=backoff_seconds))
        with self._lock, self._connection:
            if item.version != expected_version:
                raise InvalidTransition(
                    f"versione attesa {expected_version}, trovata {item.version}"
                )
            validate_transition(item.state, RunState.RETRY_SCHEDULED)
            self._connection.execute(
                """
                UPDATE work_items
                SET state = 'retry_scheduled', version = version + 1, last_error = ?,
                    available_at = ?, lease_owner = NULL, lease_expires_at = NULL, updated_at = ?
                WHERE id = ? AND version = ?
                """,
                (error, available, _iso(moment), item_id, expected_version),
            )
        return self._require(item_id)

    def reclaim_expired(self, *, now: datetime | None = None) -> list[str]:
        """Rimette in coda gli item ``running`` con lease scaduto (worker morto durante il run).

        È il recupero cross-process: nessun run resta bloccato in ``running`` perché il backend
        che lo teneva è stato riavviato.
        """
        stamp = _iso(now or _now())
        with self._lock, self._connection:
            rows = self._connection.execute(
                """
                SELECT id FROM work_items
                WHERE state = 'running' AND lease_expires_at IS NOT NULL
                  AND lease_expires_at <= ?
                """,
                (stamp,),
            ).fetchall()
            ids = [row["id"] for row in rows]
            for item_id in ids:
                self._connection.execute(
                    """
                    UPDATE work_items
                    SET state = 'queued', version = version + 1,
                        lease_owner = NULL, lease_expires_at = NULL, updated_at = ?
                    WHERE id = ?
                    """,
                    (stamp, item_id),
                )
        return ids

    def get(self, item_id: str) -> WorkItem | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM work_items WHERE id = ?", (item_id,)
            ).fetchone()
        return self._to_item(row) if row is not None else None

    def _require(self, item_id: str) -> WorkItem:
        item = self.get(item_id)
        if item is None:
            raise KeyError(item_id)
        return item

    @staticmethod
    def _to_item(row: sqlite3.Row) -> WorkItem:
        return WorkItem(
            id=row["id"],
            kind=row["kind"],
            state=RunState(row["state"]),
            version=row["version"],
            payload=json.loads(row["payload_json"] or "{}"),
            run_id=row["run_id"],
            session_id=row["session_id"],
            idempotency_key=row["idempotency_key"],
            attempts=row["attempts"],
            max_attempts=row["max_attempts"],
            available_at=row["available_at"],
            lease_owner=row["lease_owner"],
            lease_expires_at=row["lease_expires_at"],
            last_error=row["last_error"],
        )

    # ---- interrupt persistiti ------------------------------------------------

    def record_interrupt(
        self,
        *,
        run_id: str,
        kind: str,
        payload: dict[str, Any],
        work_item_id: str | None = None,
        expires_at: str | None = None,
    ) -> Interrupt:
        """Persiste un'approvazione o user action pendente.

        Il payload va passato GIÀ redatto: un'approvazione può contenere il comando o
        argomenti sensibili, e non deve entrare in chiaro nello storage (§10.2 dell'analisi).
        """
        interrupt_id = str(uuid.uuid4())
        now = _iso(_now())
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO interrupts(
                    id, run_id, work_item_id, kind, payload_json, status, created_at, expires_at
                )
                VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)
                """,
                (
                    interrupt_id,
                    run_id,
                    work_item_id,
                    kind,
                    json.dumps(payload, ensure_ascii=False),
                    now,
                    expires_at,
                ),
            )
        interrupt = self.get_interrupt(interrupt_id)
        assert interrupt is not None
        return interrupt

    def resolve_interrupt(
        self,
        interrupt_id: str,
        *,
        resolution: dict[str, Any],
        resolved_by: str,
        resolution_version: int = 1,
    ) -> Interrupt:
        """Registra la risposta a un interrupt, in modo idempotente.

        La chiave (run_id + interrupt_id + versione risoluzione) impedisce che una doppia
        conferma — utente che clicca due volte, retry di rete — risolva due volte.
        """
        with self._lock, self._connection:
            row = self._connection.execute(
                "SELECT * FROM interrupts WHERE id = ?", (interrupt_id,)
            ).fetchone()
            if row is None:
                raise KeyError(interrupt_id)
            if row["status"] == "resolved":
                # Già risolto: idempotente, restituiamo lo stato esistente senza riscrivere.
                resolved = self.get_interrupt(interrupt_id)
                assert resolved is not None
                return resolved
            key = idempotency_key(row["run_id"], interrupt_id, resolution_version)
            self._connection.execute(
                """
                UPDATE interrupts
                SET status = 'resolved', resolution_json = ?, resolved_by = ?,
                    resolved_at = ?, idempotency_key = ?
                WHERE id = ?
                """,
                (
                    json.dumps(resolution, ensure_ascii=False),
                    resolved_by,
                    _iso(_now()),
                    key,
                    interrupt_id,
                ),
            )
        resolved = self.get_interrupt(interrupt_id)
        assert resolved is not None
        return resolved

    def all_pending_interrupts(self) -> list[Interrupt]:
        """Tutti gli interrupt ancora pendenti, su ogni run. Dopo un riavvio mostra cosa era in
        attesa dell'utente e non è mai stato risolto — la prova che la persistenza sopravvive."""
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM interrupts WHERE status = 'pending' ORDER BY created_at"
            ).fetchall()
        return [self._to_interrupt(row) for row in rows]

    def pending_interrupts(self, run_id: str) -> list[Interrupt]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM interrupts WHERE run_id = ? AND status = 'pending' "
                "ORDER BY created_at",
                (run_id,),
            ).fetchall()
        return [self._to_interrupt(row) for row in rows]

    def get_interrupt(self, interrupt_id: str) -> Interrupt | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM interrupts WHERE id = ?", (interrupt_id,)
            ).fetchone()
        return self._to_interrupt(row) if row is not None else None

    @staticmethod
    def _to_interrupt(row: sqlite3.Row) -> Interrupt:
        resolution_raw = row["resolution_json"]
        return Interrupt(
            id=row["id"],
            run_id=row["run_id"],
            work_item_id=row["work_item_id"],
            kind=row["kind"],
            payload=json.loads(row["payload_json"] or "{}"),
            status=row["status"],
            created_at=row["created_at"],
            expires_at=row["expires_at"],
            resolved_at=row["resolved_at"],
            resolution=json.loads(resolution_raw) if resolution_raw else None,
            resolved_by=row["resolved_by"],
        )

    def close(self) -> None:
        with self._lock:
            self._connection.close()
