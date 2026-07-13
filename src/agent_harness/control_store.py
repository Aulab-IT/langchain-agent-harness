from __future__ import annotations

import json
import shutil
import sqlite3
import threading
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from agent_harness.config import SKILLS_LOCK, Settings
from agent_harness.pricing import ModelCallUsage, PriceEntry, PricingCatalog


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


# Cartelle di dipendenze/cache che l'agente crea come artefatti interni: non sono output
# e non vanno mostrate nel pannello File né allegate in chat.
_VENDORED_DIRS = frozenset(
    {
        "__pycache__",
        "pycache",
        "node_modules",
        "site-packages",
        "dist-info",
        ".git",
        ".ipynb_checkpoints",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
    }
)

# Estensioni di artefatti compilati/bytecode: rumore indipendente dal nome della cartella
# (es. un pycache prefix genera migliaia di .pyc fuori da __pycache__).
_ARTIFACT_SUFFIXES = frozenset(
    {".pyc", ".pyo", ".pyd", ".so", ".o", ".a", ".dylib", ".class", ".egg-info"}
)

# Sottocartella convenzionale per i deliverable finali: se presente, la chat allega solo
# questi file (gli intermedi restano nel workspace ma non invadono la conversazione).
OUTPUT_DIR = "output"


def _is_surfaced_file(relative: Path) -> bool:
    """True se il file va mostrato all'utente (non è nascosto, vendored o compilato)."""
    if relative.suffix.lower() in _ARTIFACT_SUFFIXES:
        return False
    for part in relative.parts:
        if part.startswith("."):
            return False
        if part in _VENDORED_DIRS:
            return False
    return True


class ControlStore:
    """Persistent control-plane state and session-isolated workspaces."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.settings.ensure_directories()
        self.path = settings.state_dir / "control.sqlite"
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        # WAL: due sessioni attive scrivono eventi in parallelo. Senza WAL un lettore
        # blocca lo scrittore e lo stream SSE di una sessione stalla durante il run
        # dell'altra. busy_timeout evita che una contesa breve diventi "database is locked".
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._connection.execute("PRAGMA busy_timeout = 5000")
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._setup()

    def _setup(self) -> None:
        with self._lock, self._connection:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    run_id TEXT,
                    role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system')),
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    error TEXT,
                    usage_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
                    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS triggers (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL CHECK(kind IN ('cron', 'webhook')),
                    name TEXT NOT NULL,
                    cron_expr TEXT,
                    token TEXT,
                    goal_template TEXT NOT NULL,
                    session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    last_fired_at TEXT
                );
                CREATE TABLE IF NOT EXISTS model_calls (
                    id TEXT PRIMARY KEY,
                    run_id TEXT REFERENCES runs(id) ON DELETE CASCADE,
                    session_id TEXT REFERENCES sessions(id) ON DELETE CASCADE,
                    iteration INTEGER NOT NULL DEFAULT 0,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    tier TEXT,
                    execution_kind TEXT NOT NULL DEFAULT 'cloud',
                    input_tokens INTEGER NOT NULL DEFAULT 0,
                    cached_input_tokens INTEGER NOT NULL DEFAULT 0,
                    output_tokens INTEGER NOT NULL DEFAULT 0,
                    reasoning_tokens INTEGER NOT NULL DEFAULT 0,
                    input_cost TEXT NOT NULL DEFAULT '0',
                    output_cost TEXT NOT NULL DEFAULT '0',
                    reasoning_cost TEXT NOT NULL DEFAULT '0',
                    total_cost TEXT NOT NULL DEFAULT '0',
                    effective_local_cost TEXT,
                    currency TEXT NOT NULL DEFAULT 'USD',
                    pricing_version TEXT NOT NULL DEFAULT '',
                    usage_source TEXT NOT NULL DEFAULT 'provider',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS pricing_catalog (
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    version TEXT NOT NULL,
                    input_price TEXT NOT NULL,
                    output_price TEXT NOT NULL,
                    cached_input_price TEXT NOT NULL DEFAULT '0',
                    reasoning_price TEXT NOT NULL DEFAULT '0',
                    currency TEXT NOT NULL DEFAULT 'USD',
                    source TEXT NOT NULL DEFAULT 'config',
                    valid_from TEXT NOT NULL DEFAULT '',
                    valid_to TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY (provider, model, version, valid_from)
                );
                CREATE TABLE IF NOT EXISTS notifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT,
                    run_id TEXT,
                    type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    read INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_notifications_unread
                    ON notifications(read, id);
                CREATE INDEX IF NOT EXISTS idx_messages_session
                    ON messages(session_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_runs_session
                    ON runs(session_id, started_at);
                CREATE INDEX IF NOT EXISTS idx_events_run
                    ON events(run_id, id);
                CREATE INDEX IF NOT EXISTS idx_triggers_token
                    ON triggers(token);
                CREATE INDEX IF NOT EXISTS idx_model_calls_run
                    ON model_calls(run_id, created_at);
                """
            )
            self._connection.execute(
                """
                UPDATE runs
                SET status = 'failed',
                    completed_at = ?,
                    error = 'Backend riavviato durante esecuzione.'
                WHERE status IN ('queued', 'running', 'waiting_approval', 'waiting_action')
                """,
                (utc_now(),),
            )
            columns = {
                row["name"]
                for row in self._connection.execute("PRAGMA table_info(messages)")
            }
            if "attachments_json" not in columns:
                self._connection.execute(
                    "ALTER TABLE messages ADD COLUMN attachments_json TEXT NOT NULL DEFAULT '[]'"
                )
            # Il modello che ha davvero risposto, così il badge in chat non deve indovinarlo.
            if "model" not in columns:
                self._connection.execute("ALTER TABLE messages ADD COLUMN model TEXT")
            session_columns = {
                row["name"]
                for row in self._connection.execute("PRAGMA table_info(sessions)")
            }
            if "auto_approve" not in session_columns:
                self._connection.execute(
                    "ALTER TABLE sessions ADD COLUMN auto_approve INTEGER NOT NULL DEFAULT 0"
                )
            if "model_override" not in session_columns:
                self._connection.execute(
                    "ALTER TABLE sessions ADD COLUMN model_override TEXT NOT NULL DEFAULT 'auto'"
                )
            # La scala binaria (default/strong) è diventata a tre gradini: le sessioni esistenti
            # si rimappano sugli estremi, che è dove l'utente le aveva messe.
            self._connection.execute(
                "UPDATE sessions SET model_override = 'low' WHERE model_override = 'default'"
            )
            self._connection.execute(
                "UPDATE sessions SET model_override = 'high' WHERE model_override = 'strong'"
            )
            trigger_columns = {
                row["name"]
                for row in self._connection.execute("PRAGMA table_info(triggers)")
            }
            # `0 9 * * *` sono le nove nel fuso di chi ha creato il trigger, non in UTC.
            if "timezone" not in trigger_columns:
                self._connection.execute(
                    "ALTER TABLE triggers ADD COLUMN timezone TEXT NOT NULL DEFAULT 'UTC'"
                )
            # Criterio di uscita del loop, proprio di questo trigger.
            if "success_criteria" not in trigger_columns:
                self._connection.execute(
                    "ALTER TABLE triggers ADD COLUMN success_criteria TEXT NOT NULL DEFAULT ''"
                )
            # Politica di approvazione del trigger: 0 = richiede conferma, 1 = autonomo (la sua
            # sessione va in auto-approve a ogni fire). Default 0: un cron non gira comandi
            # non sorvegliati se non lo si è scelto. La rete richiede comunque sempre conferma.
            if "auto_approve" not in trigger_columns:
                self._connection.execute(
                    "ALTER TABLE triggers ADD COLUMN auto_approve INTEGER NOT NULL DEFAULT 0"
                )
            # Gradino modello forzato per i run del trigger: 'auto' lascia decidere al router,
            # altrimenti 'low'/'mid'/'high'. Un cron di classificazione vuole un modello capace
            # senza aspettare l'escalation, che sul nano può sbagliare al primo colpo.
            if "model_tier" not in trigger_columns:
                self._connection.execute(
                    "ALTER TABLE triggers ADD COLUMN model_tier TEXT NOT NULL DEFAULT 'auto'"
                )
            # Risposta diretta: 1 = il run risponde solo con testo (niente file/verifica/tool),
            # per webhook che vogliono una classificazione/sintesi, non un artefatto nel workspace.
            if "text_response" not in trigger_columns:
                self._connection.execute(
                    "ALTER TABLE triggers ADD COLUMN text_response INTEGER NOT NULL DEFAULT 0"
                )

    def create_session(self, title: str = "Nuova sessione") -> dict[str, Any]:
        session_id = str(uuid.uuid4())
        now = utc_now()
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT INTO sessions(id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (session_id, title.strip()[:120] or "Nuova sessione", now, now),
            )
        self.prepare_session_root(session_id)
        return self.get_session(session_id)

    def session_exists(self, session_id: str) -> bool:
        with self._lock:
            row = self._connection.execute(
                "SELECT 1 FROM sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
        return row is not None

    def list_all_session_ids(self) -> list[str]:
        """Tutti gli id sessione, senza limite: usato per lo sweep sandbox (orfani/inattività)."""
        with self._lock:
            rows = self._connection.execute("SELECT id FROM sessions").fetchall()
        return [row["id"] for row in rows]

    @staticmethod
    def _session(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["auto_approve"] = bool(item.get("auto_approve", 0))
        return item

    def get_session(self, session_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT s.*,
                       (SELECT status FROM runs r WHERE r.session_id = s.id
                        ORDER BY started_at DESC LIMIT 1) AS last_status
                FROM sessions s WHERE s.id = ?
                """,
                (session_id,),
            ).fetchone()
        if row is None:
            raise KeyError(session_id)
        return self._session(row)

    def list_sessions(self, search: str = "") -> list[dict[str, Any]]:
        query = """
            SELECT s.*,
                   (SELECT content FROM messages m WHERE m.session_id = s.id
                    ORDER BY created_at DESC LIMIT 1) AS preview,
                   (SELECT status FROM runs r WHERE r.session_id = s.id
                    ORDER BY started_at DESC LIMIT 1) AS last_status
            FROM sessions s
        """
        parameters: tuple[Any, ...] = ()
        if search:
            query += """
                WHERE s.title LIKE ?
                   OR EXISTS (
                       SELECT 1 FROM messages m
                       WHERE m.session_id = s.id AND m.content LIKE ?
                   )
            """
            term = f"%{search[:200]}%"
            parameters = (term, term)
        query += " ORDER BY s.updated_at DESC LIMIT 100"
        with self._lock:
            rows = self._connection.execute(query, parameters).fetchall()
        return [self._session(row) for row in rows]

    def rename_session(self, session_id: str, title: str) -> dict[str, Any]:
        with self._lock, self._connection:
            cursor = self._connection.execute(
                "UPDATE sessions SET title = ?, updated_at = ? WHERE id = ?",
                (title.strip()[:120] or "Nuova sessione", utc_now(), session_id),
            )
        if cursor.rowcount == 0:
            raise KeyError(session_id)
        return self.get_session(session_id)

    def set_session_auto_approve(self, session_id: str, enabled: bool) -> dict[str, Any]:
        """Attiva/disattiva l'autonomia della sessione: se attiva, le richieste di
        approvazione (es. docker_exec) vengono accettate subito, senza fermare il run."""
        with self._lock, self._connection:
            cursor = self._connection.execute(
                "UPDATE sessions SET auto_approve = ? WHERE id = ?",
                (1 if enabled else 0, session_id),
            )
        if cursor.rowcount == 0:
            raise KeyError(session_id)
        return self.get_session(session_id)

    def set_session_model_override(self, session_id: str, override: str) -> dict[str, Any]:
        """Forza il modello per l'intera sessione, o restituisce la scelta al router (`auto`)."""
        if override not in {"auto", "low", "mid", "high"}:
            raise ValueError(f"Override modello non valido: {override}")
        with self._lock, self._connection:
            cursor = self._connection.execute(
                "UPDATE sessions SET model_override = ? WHERE id = ?",
                (override, session_id),
            )
        if cursor.rowcount == 0:
            raise KeyError(session_id)
        return self.get_session(session_id)

    def delete_session(self, session_id: str) -> None:
        with self._lock, self._connection:
            cursor = self._connection.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        if cursor.rowcount == 0:
            raise KeyError(session_id)
        shutil.rmtree(self.session_root(session_id), ignore_errors=True)

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        *,
        run_id: str | None = None,
        attachments: list[str] | None = None,
        model: str | None = None,
    ) -> dict[str, Any]:
        message_id = str(uuid.uuid4())
        now = utc_now()
        attachment_names = list(attachments or [])
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO messages(
                    id, session_id, run_id, role, content, created_at, attachments_json, model
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message_id,
                    session_id,
                    run_id,
                    role,
                    content,
                    now,
                    json.dumps(attachment_names, ensure_ascii=False),
                    model,
                ),
            )
            self._connection.execute(
                "UPDATE sessions SET updated_at = ? WHERE id = ?",
                (now, session_id),
            )
            count = self._connection.execute(
                "SELECT COUNT(*) FROM messages WHERE session_id = ?",
                (session_id,),
            ).fetchone()[0]
            if role == "user" and count == 1:
                title = " ".join(content.split())[:60]
                self._connection.execute(
                    "UPDATE sessions SET title = ? WHERE id = ?",
                    (title or "Nuova sessione", session_id),
                )
        return {
            "id": message_id,
            "session_id": session_id,
            "run_id": run_id,
            "role": role,
            "content": content,
            "created_at": now,
            "attachments": attachment_names,
            "model": model,
        }

    def list_messages(self, session_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM messages WHERE session_id = ? ORDER BY created_at, rowid",
                (session_id,),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["attachments"] = json.loads(item.pop("attachments_json", None) or "[]")
            result.append(item)
        return result

    def create_run(self, session_id: str) -> dict[str, Any]:
        run_id = str(uuid.uuid4())
        now = utc_now()
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO runs(id, session_id, status, started_at)
                VALUES (?, ?, 'queued', ?)
                """,
                (run_id, session_id, now),
            )
        return self.get_run(run_id)

    def get_run(self, run_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._connection.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        return self._run(row)

    @staticmethod
    def _run(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["usage"] = {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "output_tokens_per_second": 0,
            "context_categories": [],
            "estimated_context": True,
            **json.loads(result.pop("usage_json") or "{}"),
        }
        return result

    def recent_terminal_runs(self, *, limit: int = 100) -> list[dict[str, Any]]:
        """Ultimi run conclusi, usati come finestra stabile dal loop di miglioramento."""
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT * FROM runs
                WHERE status IN ('completed', 'failed', 'cancelled')
                ORDER BY started_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._run(row) for row in reversed(rows)]

    def latest_run(self, session_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT id FROM runs WHERE session_id = ? ORDER BY started_at DESC LIMIT 1",
                (session_id,),
            ).fetchone()
        return self.get_run(row["id"]) if row else None

    def update_run(
        self,
        run_id: str,
        *,
        status: str,
        error: str | None = None,
        usage: dict[str, Any] | None = None,
    ) -> None:
        terminal = status in {"completed", "failed", "cancelled"}
        with self._lock, self._connection:
            self._connection.execute(
                """
                UPDATE runs
                SET status = ?, completed_at = ?, error = ?, usage_json = ?
                WHERE id = ?
                """,
                (
                    status,
                    utc_now() if terminal else None,
                    error,
                    json.dumps(usage or {}, ensure_ascii=False),
                    run_id,
                ),
            )

    def cost_summary(self, *, recent: int = 20) -> dict[str, Any]:
        """Costo totale, per sessione e dei run recenti, dal campo ``cost_usd`` nell'usage.

        Somma i costi già registrati sui run (nessun ricalcolo): il denaro resta ``Decimal`` per
        non accumulare errore, e viene serializzato a stringa solo in uscita.
        """
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT r.id, r.session_id, r.completed_at, r.usage_json, s.title AS session_title
                FROM runs r LEFT JOIN sessions s ON s.id = r.session_id
                WHERE r.usage_json LIKE '%cost_usd%'
                ORDER BY r.completed_at DESC
                """
            ).fetchall()
        total = Decimal(0)
        by_session: dict[str, dict[str, Any]] = {}
        recent_runs: list[dict[str, Any]] = []
        for row in rows:
            try:
                cost = Decimal(str(json.loads(row["usage_json"] or "{}").get("cost_usd", "0")))
            except (ArithmeticError, ValueError, TypeError):
                cost = Decimal(0)
            total += cost
            sid = row["session_id"]
            bucket = by_session.setdefault(
                sid,
                {
                    "session_id": sid,
                    "title": row["session_title"] or "Sessione",
                    "cost": Decimal(0),
                    "runs": 0,
                },
            )
            bucket["cost"] += cost
            bucket["runs"] += 1
            if len(recent_runs) < recent:
                recent_runs.append(
                    {
                        "run_id": row["id"],
                        "session_id": sid,
                        "title": row["session_title"] or "Sessione",
                        "cost_usd": str(cost),
                        "completed_at": row["completed_at"],
                    }
                )
        sessions = sorted(
            (
                {**bucket, "cost_usd": str(bucket.pop("cost"))}
                for bucket in by_session.values()
            ),
            key=lambda item: Decimal(item["cost_usd"]),
            reverse=True,
        )
        return {"total_usd": str(total), "sessions": sessions, "recent": recent_runs}

    def record_model_call(
        self,
        usage: ModelCallUsage,
        *,
        run_id: str | None = None,
        session_id: str | None = None,
        iteration: int = 0,
        tier: str | None = None,
    ) -> str:
        """Registra una singola chiamata al modello nel ledger ``model_calls``.

        Una riga per chiamata, immutabile: gli aggregati per run/sessione/provider si
        ricavano sommando queste righe, mai ricalcolando con prezzi nuovi. I costi sono
        stringhe (``Decimal`` serializzato) per non reintrodurre l'errore del ``float``.
        """
        row = usage.to_row()
        call_id = str(uuid.uuid4())
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO model_calls(
                    id, run_id, session_id, iteration, provider, model, tier,
                    execution_kind, input_tokens, cached_input_tokens, output_tokens,
                    reasoning_tokens, input_cost, output_cost, reasoning_cost, total_cost,
                    effective_local_cost, currency, pricing_version, usage_source, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    call_id,
                    run_id,
                    session_id,
                    iteration,
                    row["provider"],
                    row["model"],
                    tier,
                    row["execution_kind"],
                    row["input_tokens"],
                    row["cached_input_tokens"],
                    row["output_tokens"],
                    row["reasoning_tokens"],
                    row["input_cost"],
                    row["output_cost"],
                    row["reasoning_cost"],
                    row["total_cost"],
                    row["effective_local_cost"],
                    row["currency"],
                    row["pricing_version"],
                    row["usage_source"],
                    utc_now(),
                ),
            )
        return call_id

    def list_run_model_calls(self, run_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM model_calls WHERE run_id = ? ORDER BY created_at, rowid",
                (run_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def upsert_pricing_catalog(self, catalog: PricingCatalog) -> None:
        """Persiste il listino versionato. Idempotente sulla chiave
        (provider, modello, versione, valid_from): rieseguirlo non duplica righe."""
        with self._lock, self._connection:
            for entry in catalog.entries():
                self._connection.execute(
                    """
                    INSERT OR REPLACE INTO pricing_catalog(
                        provider, model, version, input_price, output_price,
                        cached_input_price, reasoning_price, currency, source,
                        valid_from, valid_to
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        entry.provider,
                        entry.model,
                        entry.version,
                        str(entry.input_price),
                        str(entry.output_price),
                        str(entry.cached_input_price),
                        str(entry.reasoning_price),
                        entry.currency,
                        entry.source,
                        entry.valid_from,
                        entry.valid_to,
                    ),
                )

    def load_pricing_catalog(self) -> PricingCatalog:
        with self._lock:
            rows = self._connection.execute("SELECT * FROM pricing_catalog").fetchall()
        entries = [
            PriceEntry(
                provider=row["provider"],
                model=row["model"],
                input_price=Decimal(row["input_price"]),
                output_price=Decimal(row["output_price"]),
                cached_input_price=Decimal(row["cached_input_price"]),
                reasoning_price=Decimal(row["reasoning_price"]),
                currency=row["currency"],
                source=row["source"],
                version=row["version"],
                valid_from=row["valid_from"],
                valid_to=row["valid_to"],
            )
            for row in rows
        ]
        return PricingCatalog(entries)

    def add_event(
        self,
        run_id: str,
        session_id: str,
        event_type: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = utc_now()
        clean_payload = payload or {}
        with self._lock, self._connection:
            cursor = self._connection.execute(
                """
                INSERT INTO events(run_id, session_id, type, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (run_id, session_id, event_type, json.dumps(clean_payload), now),
            )
        return {
            "id": cursor.lastrowid,
            "run_id": run_id,
            "session_id": session_id,
            "type": event_type,
            "payload": clean_payload,
            "created_at": now,
        }

    def add_notification(
        self,
        *,
        type: str,
        title: str,
        session_id: str | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        """Registra una notifica persistente: ciò che l'utente deve vedere quando torna.

        È il cuore del pattern «cowork»: lanci un run, ti allontani, e al ritorno trovi qui cosa
        è successo mentre non guardavi (completato, fallito, in attesa di te).
        """
        now = utc_now()
        with self._lock, self._connection:
            cursor = self._connection.execute(
                """
                INSERT INTO notifications(session_id, run_id, type, title, read, created_at)
                VALUES (?, ?, ?, ?, 0, ?)
                """,
                (session_id, run_id, type, title[:200], now),
            )
        return {
            "id": cursor.lastrowid,
            "session_id": session_id,
            "run_id": run_id,
            "type": type,
            "title": title[:200],
            "read": False,
            "created_at": now,
        }

    def list_notifications(
        self, *, unread_only: bool = False, limit: int = 100
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM notifications"
        if unread_only:
            query += " WHERE read = 0"
        query += " ORDER BY id DESC LIMIT ?"
        with self._lock:
            rows = self._connection.execute(query, (limit,)).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["read"] = bool(item["read"])
            result.append(item)
        return result

    def unread_notification_count(self) -> int:
        with self._lock:
            row = self._connection.execute(
                "SELECT COUNT(*) AS n FROM notifications WHERE read = 0"
            ).fetchone()
        return int(row["n"])

    def mark_notifications_read(self, ids: list[int] | None = None) -> int:
        """Segna come lette le notifiche indicate, o tutte se ``ids`` è None. Ritorna quante."""
        with self._lock, self._connection:
            if ids is None:
                cursor = self._connection.execute(
                    "UPDATE notifications SET read = 1 WHERE read = 0"
                )
            elif ids:
                placeholders = ",".join("?" for _ in ids)
                cursor = self._connection.execute(
                    f"UPDATE notifications SET read = 1 WHERE id IN ({placeholders})",
                    tuple(ids),
                )
            else:
                return 0
        return cursor.rowcount

    def list_events(
        self,
        run_id: str,
        *,
        after_id: int = 0,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT * FROM events
                WHERE run_id = ? AND id > ?
                ORDER BY id LIMIT ?
                """,
                (run_id, after_id, limit),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["payload"] = json.loads(item.pop("payload_json"))
            result.append(item)
        return result

    def list_session_events(
        self,
        session_id: str,
        *,
        limit: int = 2_000,
    ) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT * FROM events
                WHERE session_id = ?
                ORDER BY id DESC LIMIT ?
                """,
                (session_id, limit),
            ).fetchall()
        result = []
        for row in reversed(rows):
            item = dict(row)
            item["payload"] = json.loads(item.pop("payload_json"))
            result.append(item)
        return result

    def event_history(
        self,
        *,
        run_id: str | None = None,
        session_id: str | None = None,
        before_id: int | None = None,
        limit: int = 1_000,
        include_deltas: bool = False,
    ) -> tuple[list[dict[str, Any]], bool]:
        """Pagina cronologica di eventi, letta a ritroso senza limiti silenziosi.

        Una sola tra ``run_id`` e ``session_id`` deve essere valorizzata. La query legge
        ``limit + 1`` righe per dichiarare esplicitamente se esiste una pagina precedente.
        I delta di streaming sono trasporto effimero e restano esclusi dallo storico operativo.
        """
        if (run_id is None) == (session_id is None):
            raise ValueError("Specificare esattamente run_id oppure session_id.")
        field = "run_id" if run_id is not None else "session_id"
        value = run_id if run_id is not None else session_id
        clauses = [f"{field} = ?"]
        params: list[Any] = [value]
        if before_id is not None:
            clauses.append("id < ?")
            params.append(before_id)
        if not include_deltas:
            clauses.append("type != 'assistant.delta'")
        params.append(limit + 1)
        query = f"""
            SELECT * FROM events
            WHERE {' AND '.join(clauses)}
            ORDER BY id DESC LIMIT ?
        """
        with self._lock:
            rows = self._connection.execute(query, tuple(params)).fetchall()
        has_more_before = len(rows) > limit
        page = rows[:limit]
        result = []
        for row in reversed(page):
            item = dict(row)
            item["payload"] = json.loads(item.pop("payload_json"))
            result.append(item)
        return result, has_more_before

    def delete_run_events(self, run_id: str, event_types: set[str]) -> int:
        """Rimuove eventi effimeri già consolidati nel messaggio finale."""
        if not event_types:
            return 0
        placeholders = ",".join("?" for _ in event_types)
        with self._lock, self._connection:
            cursor = self._connection.execute(
                f"DELETE FROM events WHERE run_id = ? AND type IN ({placeholders})",
                (run_id, *sorted(event_types)),
            )
        return cursor.rowcount

    def recent_events(self, *, limit: int = 1_000) -> list[dict[str, Any]]:
        """Ultimi eventi su tutte le sessioni, per l'analisi hill-climbing."""
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM events ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        result = []
        for row in reversed(rows):
            item = dict(row)
            item["payload"] = json.loads(item.pop("payload_json"))
            result.append(item)
        return result

    def events_for_runs(
        self,
        run_ids: list[str],
        *,
        event_types: tuple[str, ...] | None = None,
    ) -> list[dict[str, Any]]:
        """Eventi correlati a run espliciti; evita finestre distorte dagli eventi streaming."""
        if not run_ids:
            return []
        run_placeholders = ",".join("?" for _ in run_ids)
        parameters: list[Any] = list(run_ids)
        query = f"SELECT * FROM events WHERE run_id IN ({run_placeholders})"
        if event_types:
            type_placeholders = ",".join("?" for _ in event_types)
            query += f" AND type IN ({type_placeholders})"
            parameters.extend(event_types)
        query += " ORDER BY id"
        with self._lock:
            rows = self._connection.execute(query, parameters).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["payload"] = json.loads(item.pop("payload_json"))
            result.append(item)
        return result

    def session_root(self, session_id: str) -> Path:
        return self.settings.state_dir / "sessions" / session_id

    def workspace_dir(self, session_id: str) -> Path:
        return self.session_root(session_id) / "workspace"

    def prepare_session_root(self, session_id: str) -> Path:
        root = self.session_root(session_id)
        workspace = root / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)
        (root / "memories").mkdir(exist_ok=True)
        # Ricopia le skill da zero a ogni run, così modifiche ed eliminazioni dal pannello
        # si riflettono nel run successivo. Il lock è di processo e serializza le copie: due
        # sessioni che partono insieme leggono lo stesso albero sorgente, e senza di esso una
        # skill installata a metà copia finirebbe nella sessione a pezzi.
        with SKILLS_LOCK:
            shutil.rmtree(root / "skills", ignore_errors=True)
            (root / "skills").mkdir(exist_ok=True)
            if self.settings.skills_dir.exists():
                shutil.copytree(self.settings.skills_dir, root / "skills", dirs_exist_ok=True)
        # La memoria di sessione si semina UNA VOLTA dal template di progetto. Ricopiarla a
        # ogni run distruggerebbe gli apprendimenti che l'agente ci scrive dentro.
        memory_file = root / "memories" / "AGENTS.md"
        if not memory_file.exists():
            source_memory = self.settings.project_root / "memories" / "AGENTS.md"
            if source_memory.exists():
                shutil.copy2(source_memory, memory_file)
            else:
                memory_file.write_text("# Memoria sessione\n", encoding="utf-8")
        return root

    def cap_session_memory(self, session_id: str, max_chars: int) -> bool:
        """Tronca ``memories/AGENTS.md`` se supera ``max_chars``. Ritorna True se ha troncato.

        L'agente può scrivere nella propria memoria, e una memoria che cresce senza limite è un
        prompt che cresce a ogni run. Quando il file sfora, si tiene la testa (le sezioni curate
        e gli apprendimenti più vecchi e consolidati) e si sostituisce la coda con un marcatore,
        così il taglio è esplicito invece che silenzioso. Il chiamante emette l'evento visibile.
        """
        memory_file = self.session_root(session_id) / "memories" / "AGENTS.md"
        if not memory_file.is_file():
            return False
        content = memory_file.read_text(encoding="utf-8")
        if len(content) <= max_chars:
            return False
        marker = "\n\n<!-- memoria troncata al limite di dimensione -->\n"
        head = content[: max(0, max_chars - len(marker))]
        memory_file.write_text(head + marker, encoding="utf-8")
        return True

    def list_files(self, session_id: str) -> list[dict[str, Any]]:
        workspace = self.workspace_dir(session_id)
        result: list[dict[str, Any]] = []
        if not workspace.exists():
            return result
        for path in sorted(workspace.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            try:
                relative = path.relative_to(workspace)
                stat = path.stat()
            except (OSError, ValueError):
                continue
            # Nasconde dipendenze e cache installate dall'agente (es. /workspace/.pylib,
            # __pycache__, node_modules): sono artefatti interni, non output da mostrare.
            if not _is_surfaced_file(relative):
                continue
            result.append(
                {
                    "name": relative.as_posix(),
                    "size": stat.st_size,
                    "type": path.suffix.lstrip(".").upper(),
                    "modified_at": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(),
                }
            )
            if len(result) >= 500:
                break
        return result

    @staticmethod
    def _trigger(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["enabled"] = bool(item["enabled"])
        item["auto_approve"] = bool(item.get("auto_approve", 0))
        item["text_response"] = bool(item.get("text_response", 0))
        return item

    def create_trigger(
        self,
        *,
        kind: str,
        name: str,
        goal_template: str,
        cron_expr: str | None = None,
        session_id: str | None = None,
        token: str | None = None,
        timezone: str = "UTC",
        success_criteria: str = "",
        auto_approve: bool = False,
        model_tier: str = "auto",
        text_response: bool = False,
    ) -> dict[str, Any]:
        trigger_id = str(uuid.uuid4())
        now = utc_now()
        tier = model_tier if model_tier in {"auto", "low", "mid", "high"} else "auto"
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO triggers(
                    id, kind, name, cron_expr, token, goal_template,
                    session_id, enabled, created_at, timezone, success_criteria,
                    auto_approve, model_tier, text_response
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trigger_id,
                    kind,
                    name.strip()[:120] or kind,
                    cron_expr,
                    token,
                    goal_template,
                    session_id,
                    now,
                    timezone,
                    success_criteria,
                    1 if auto_approve else 0,
                    tier,
                    1 if text_response else 0,
                ),
            )
        return self.get_trigger(trigger_id)

    def get_trigger(self, trigger_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM triggers WHERE id = ?",
                (trigger_id,),
            ).fetchone()
        if row is None:
            raise KeyError(trigger_id)
        return self._trigger(row)

    def get_trigger_by_token(self, token: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM triggers WHERE token = ?",
                (token,),
            ).fetchone()
        return self._trigger(row) if row else None

    def list_triggers(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM triggers ORDER BY created_at DESC LIMIT 200",
            ).fetchall()
        return [self._trigger(row) for row in rows]

    def enabled_cron_triggers(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM triggers WHERE kind = 'cron' AND enabled = 1",
            ).fetchall()
        return [self._trigger(row) for row in rows]

    def set_trigger_enabled(self, trigger_id: str, enabled: bool) -> dict[str, Any]:
        with self._lock, self._connection:
            cursor = self._connection.execute(
                "UPDATE triggers SET enabled = ? WHERE id = ?",
                (1 if enabled else 0, trigger_id),
            )
        if cursor.rowcount == 0:
            raise KeyError(trigger_id)
        return self.get_trigger(trigger_id)

    def attach_trigger_session(self, trigger_id: str, session_id: str) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "UPDATE triggers SET session_id = ? WHERE id = ?",
                (session_id, trigger_id),
            )

    def mark_trigger_fired(self, trigger_id: str) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "UPDATE triggers SET last_fired_at = ? WHERE id = ?",
                (utc_now(), trigger_id),
            )

    def delete_trigger(self, trigger_id: str) -> None:
        with self._lock, self._connection:
            cursor = self._connection.execute(
                "DELETE FROM triggers WHERE id = ?",
                (trigger_id,),
            )
        if cursor.rowcount == 0:
            raise KeyError(trigger_id)

    def close(self) -> None:
        with self._lock:
            self._connection.close()
