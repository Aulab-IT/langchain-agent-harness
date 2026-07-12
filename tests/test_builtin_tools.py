from __future__ import annotations

from pathlib import Path

from agent_harness.builtin_tools import build_builtin_tools


def _tools(tmp_path: Path):
    skills = tmp_path / "skills"
    skills.mkdir()
    session = tmp_path / "session"
    (session / "skills").mkdir(parents=True)
    tools = build_builtin_tools(skills, session, registry_url="https://example.invalid")
    return {t.name: t for t in tools}, skills, session


def test_builtin_tools_are_the_expected_seven(tmp_path: Path) -> None:
    tools, _, _ = _tools(tmp_path)
    assert set(tools) == {
        "count_text",
        "harness_glossary",
        "skill_list",
        "skill_read",
        "skill_create",
        "skill_write_file",
        "skill_install",
    }


def test_count_text_counts_locally(tmp_path: Path) -> None:
    tools, _, _ = _tools(tmp_path)
    result = tools["count_text"].invoke({"text": "una due\ntre"})
    assert result == {"characters": 11, "words": 3, "lines": 2}


def test_glossary_known_and_unknown(tmp_path: Path) -> None:
    tools, _, _ = _tools(tmp_path)
    assert "agente" in tools["harness_glossary"].invoke({"term": "harness"})
    assert "non presente" in tools["harness_glossary"].invoke({"term": "boh"}).lower()


def test_skill_create_writes_host_and_syncs_into_session(tmp_path: Path) -> None:
    tools, skills, session = _tools(tmp_path)
    info = tools["skill_create"].invoke(
        {
            "name": "demo-skill",
            "description": "Una skill di prova per il test.",
            "body": "Passi della procedura.",
        }
    )
    assert info["name"] == "demo-skill"
    # Scritta sull'host...
    assert (skills / "demo-skill" / "SKILL.md").is_file()
    # ...e sincronizzata nella radice di sessione, così il run la vede subito.
    assert (session / "skills" / "demo-skill" / "SKILL.md").is_file()


def test_skill_list_reflects_created_skill(tmp_path: Path) -> None:
    tools, _, _ = _tools(tmp_path)
    tools["skill_create"].invoke(
        {"name": "altra-skill", "description": "Descrizione valida.", "body": "corpo"}
    )
    names = {item["name"] for item in tools["skill_list"].invoke({})}
    assert "altra-skill" in names
