import shutil
import threading
from pathlib import Path

import pytest

from agent_harness.config import SKILLS_LOCK, Settings
from agent_harness.control_store import ControlStore


def make_store(tmp_path: Path) -> ControlStore:
    (tmp_path / "skills" / "research").mkdir(parents=True)
    (tmp_path / "skills" / "research" / "SKILL.md").write_text("# Research\n")
    (tmp_path / "memories").mkdir()
    (tmp_path / "memories" / "AGENTS.md").write_text("# Memory\n")
    return ControlStore(Settings(_env_file=None, project_root=tmp_path))


def test_session_persists_messages_runs_and_events(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    session = store.create_session()
    run = store.create_run(session["id"])
    store.add_message(session["id"], "user", "Analizza", run_id=run["id"])
    event = store.add_event(run["id"], session["id"], "run.started", {"ok": True})

    assert store.get_session(session["id"])["title"] == "Analizza"
    assert store.list_messages(session["id"])[0]["content"] == "Analizza"
    assert store.list_events(run["id"])[0]["id"] == event["id"]
    assert store.list_events(run["id"])[0]["payload"] == {"ok": True}
    store.close()


def test_session_model_override_defaults_to_auto_and_rejects_junk(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    session = store.create_session()

    assert session["model_override"] == "auto"

    store.set_session_model_override(session["id"], "high")
    assert store.get_session(session["id"])["model_override"] == "high"
    store.set_session_model_override(session["id"], "mid")
    assert store.get_session(session["id"])["model_override"] == "mid"

    with pytest.raises(ValueError):
        store.set_session_model_override(session["id"], "gpt-inesistente")
    store.close()


def test_assistant_message_records_the_model_that_answered(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    session = store.create_session()

    created = store.add_message(session["id"], "assistant", "ciao", model="gpt-5.5")

    assert created["model"] == "gpt-5.5"
    assert store.list_messages(session["id"])[0]["model"] == "gpt-5.5"
    store.close()


def test_messages_without_a_model_stay_none(tmp_path: Path) -> None:
    """I messaggi anteriori al tracciamento non devono acquisire un modello inventato."""
    store = make_store(tmp_path)
    session = store.create_session()

    store.add_message(session["id"], "user", "domanda")

    assert store.list_messages(session["id"])[0]["model"] is None
    store.close()


def test_both_databases_use_wal(tmp_path: Path) -> None:
    store = make_store(tmp_path)

    mode = store._connection.execute("PRAGMA journal_mode").fetchone()[0]
    timeout = store._connection.execute("PRAGMA busy_timeout").fetchone()[0]

    assert mode.lower() == "wal"
    assert timeout > 0
    store.close()


def test_two_sessions_writing_events_in_parallel_do_not_lock_the_database(
    tmp_path: Path,
) -> None:
    """Due sessioni che scrivono e leggono insieme non si disturbano.

    Nota su cosa questo test *non* dimostra: `ControlStore` condivide una sola connessione
    protetta da un `RLock`, quindi dentro un processo gli accessi sono già serializzati e il
    test passa anche senza WAL (verificato disattivandolo). WAL e `busy_timeout` servono al
    caso multi-processo — server e CLI aperti insieme sullo stesso `control.sqlite` — e sono
    verificati da `test_both_databases_use_wal`.
    """
    store = make_store(tmp_path)
    sessions = [store.create_session(f"s{index}") for index in range(2)]
    runs = [store.create_run(session["id"]) for session in sessions]
    errors: list[Exception] = []

    def writer(index: int) -> None:
        try:
            for step in range(60):
                store.add_event(
                    runs[index]["id"], sessions[index]["id"], "tool.started", {"n": step}
                )
        except Exception as exc:
            errors.append(exc)

    def reader(index: int) -> None:
        try:
            for _ in range(60):
                store.list_events(runs[index]["id"])
                store.get_run(runs[index]["id"])
        except Exception as exc:
            errors.append(exc)

    threads = [
        *(threading.Thread(target=writer, args=(index,)) for index in range(2)),
        *(threading.Thread(target=reader, args=(index,)) for index in range(2)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    for index in range(2):
        assert len(store.list_events(runs[index]["id"])) == 60
    store.close()


def test_session_root_preparation_is_safe_while_a_skill_is_being_installed(
    tmp_path: Path,
) -> None:
    """La gara vera: una sessione copia `skills/` mentre un'altra scrittura lo sta rifacendo.

    Senza `SKILLS_LOCK`, `copytree` incontra una cartella che `install_skill` ha appena
    cancellato e sta ricreando, e solleva `FileNotFoundError`.
    """
    store = make_store(tmp_path)
    sessions = [store.create_session(f"s{index}") for index in range(3)]
    errors: list[Exception] = []
    stop = threading.Event()

    def churn() -> None:
        # Imita `_finalize_install`: rmtree della cartella skill, poi ricreazione.
        source = tmp_path / "skills" / "research"
        while not stop.is_set():
            try:
                with SKILLS_LOCK:
                    shutil.rmtree(source, ignore_errors=True)
                    source.mkdir(parents=True, exist_ok=True)
                    (source / "SKILL.md").write_text("# Research\n")
            except Exception as exc:
                errors.append(exc)

    def prepare(session_id: str) -> None:
        try:
            for _ in range(30):
                store.prepare_session_root(session_id)
        except Exception as exc:
            errors.append(exc)

    writer = threading.Thread(target=churn, daemon=True)
    writer.start()
    readers = [threading.Thread(target=prepare, args=(item["id"],)) for item in sessions]
    for thread in readers:
        thread.start()
    for thread in readers:
        thread.join()
    stop.set()
    writer.join(timeout=5)

    assert errors == []
    store.close()


def test_message_attachments_persist(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    session = store.create_session()

    store.add_message(session["id"], "user", "Analizza", attachments=["Housing.csv"])

    message = store.list_messages(session["id"])[0]
    assert message["attachments"] == ["Housing.csv"]
    store.close()


def test_message_attachments_default_empty(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    session = store.create_session()

    store.add_message(session["id"], "user", "Ciao")

    assert store.list_messages(session["id"])[0]["attachments"] == []
    store.close()


def test_auto_approve_defaults_false_and_can_be_toggled(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    session = store.create_session()

    assert store.get_session(session["id"])["auto_approve"] is False
    assert session["auto_approve"] is False

    updated = store.set_session_auto_approve(session["id"], True)
    assert updated["auto_approve"] is True
    assert store.get_session(session["id"])["auto_approve"] is True

    reverted = store.set_session_auto_approve(session["id"], False)
    assert reverted["auto_approve"] is False
    store.close()


def test_list_sessions_reflects_auto_approve(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    session = store.create_session()
    store.set_session_auto_approve(session["id"], True)

    listed = store.list_sessions()

    assert listed[0]["auto_approve"] is True
    store.close()


def test_session_root_copies_runtime_context(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    session = store.create_session()
    root = store.session_root(session["id"])

    assert (root / "workspace").is_dir()
    assert (root / "skills" / "research" / "SKILL.md").is_file()
    assert (root / "memories" / "AGENTS.md").is_file()
    store.close()


def test_improvement_window_is_bounded_by_terminal_runs(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    session = store.create_session()
    run_ids = []
    for index in range(3):
        run = store.create_run(session["id"])
        run_ids.append(run["id"])
        store.add_event(run["id"], session["id"], "assistant.delta", {"text": "x"})
        store.add_event(run["id"], session["id"], "grader.completed", {"score": index})
        store.update_run(run["id"], status="completed", usage={"total_tokens": index + 1})

    runs = store.recent_terminal_runs(limit=2)
    events = store.events_for_runs(
        [run["id"] for run in runs],
        event_types=("grader.completed",),
    )

    assert [run["id"] for run in runs] == run_ids[-2:]
    assert [event["run_id"] for event in events] == run_ids[-2:]
    assert {event["type"] for event in events} == {"grader.completed"}
    assert [run["usage"]["total_tokens"] for run in runs] == [2, 3]
    store.close()


def test_list_files_hides_dependencies_and_cache(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    session = store.create_session()
    ws = store.workspace_dir(session["id"])
    # Deliverable e artefatti reali.
    (ws / "output").mkdir()
    (ws / "output" / "report.md").write_text("ok")
    (ws / "scripts").mkdir()
    (ws / "scripts" / "fetch.py").write_text("print(1)")
    # Rumore: dipendenze installate + cache.
    (ws / ".pylib" / "cffi").mkdir(parents=True)
    (ws / ".pylib" / "cffi" / "api.py").write_text("x")
    (ws / "scripts" / "__pycache__").mkdir()
    (ws / "scripts" / "__pycache__" / "fetch.cpython-312.pyc").write_text("x")
    # Rumore da pycache-prefix: cartella non nascosta "pycache" con mirror di .pyc.
    (ws / "work" / "pycache" / "usr" / "lib").mkdir(parents=True)
    (ws / "work" / "pycache" / "usr" / "lib" / "os.cpython-312.pyc").write_text("x")
    # Bytecode sparso fuori da qualsiasi cartella cache: escluso per estensione.
    (ws / "scripts" / "fetch.cpython-312.pyc").write_text("x")

    names = {item["name"] for item in store.list_files(session["id"])}
    assert names == {"output/report.md", "scripts/fetch.py"}
    store.close()


def test_model_call_ledger_roundtrip(tmp_path: Path) -> None:
    from decimal import Decimal

    from agent_harness.pricing import ModelCallUsage

    store = make_store(tmp_path)
    session = store.create_session()
    run = store.create_run(session["id"])
    usage = ModelCallUsage(
        provider="openai",
        model="gpt-x",
        execution_kind="cloud",
        input_tokens=100,
        output_tokens=40,
        input_cost=Decimal("0.001"),
        output_cost=Decimal("0.002"),
        pricing_version="v1",
    )
    call_id = store.record_model_call(usage, run_id=run["id"], session_id=session["id"], tier="low")
    rows = store.list_run_model_calls(run["id"])
    assert len(rows) == 1
    assert rows[0]["id"] == call_id
    assert rows[0]["provider"] == "openai"
    # Il costo resta stringa (Decimal serializzato), non float.
    assert rows[0]["total_cost"] == "0.003"
    assert rows[0]["tier"] == "low"
    store.close()


def test_pricing_catalog_persist_is_idempotent(tmp_path: Path) -> None:
    from agent_harness.pricing import catalog_from_settings

    store = make_store(tmp_path)
    catalog = catalog_from_settings(Settings(_env_file=None, project_root=tmp_path))
    store.upsert_pricing_catalog(catalog)
    store.upsert_pricing_catalog(catalog)  # secondo giro non duplica
    loaded = store.load_pricing_catalog()
    assert len(loaded.entries()) == len(catalog.entries())
    store.close()
