from pathlib import Path

from agent_harness.config import Settings
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
