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
