from pathlib import Path

import pytest

from agent_harness.skills import (
    build_skill_md,
    delete_skill,
    list_skills,
    parse_frontmatter,
    read_skill,
    validate_skill,
    write_skill,
)


def test_parse_frontmatter_splits_meta_and_body() -> None:
    text = "---\nname: demo\ndescription: x\n---\n\n# Corpo\ntesto"
    front, body = parse_frontmatter(text)

    assert front == {"name": "demo", "description": "x"}
    assert body.startswith("# Corpo")


def test_validate_accepts_compliant_skill() -> None:
    errors = validate_skill("data-analysis", "data-analysis", {"description": "Cosa fa e quando."})
    assert errors == []


@pytest.mark.parametrize(
    "name",
    ["Bad-Name", "-lead", "trail-", "double--hyphen", "under_score", "a" * 65],
)
def test_validate_rejects_bad_names(name: str) -> None:
    errors = validate_skill(name, name, {"description": "valida"})
    assert errors  # almeno un errore


def test_validate_requires_name_matches_directory() -> None:
    errors = validate_skill("uno", "due", {"description": "valida"})
    assert any("coincid" in e for e in errors)


def test_validate_requires_description() -> None:
    assert any("description" in e for e in validate_skill("ok", "ok", {}))


def test_write_read_delete_roundtrip(tmp_path: Path) -> None:
    content = build_skill_md(
        "code-review", "Rivede il codice. Usala per le PR.", "# Passi\n1. Leggi."
    )
    saved = write_skill(tmp_path, "code-review", content)

    assert saved["valid"] is True
    assert saved["name"] == "code-review"

    fetched = read_skill(tmp_path, "code-review")
    assert fetched["description"].startswith("Rivede il codice")
    assert [s["name"] for s in list_skills(tmp_path)] == ["code-review"]

    delete_skill(tmp_path, "code-review")
    assert list_skills(tmp_path) == []


def test_write_rejects_invalid_frontmatter(tmp_path: Path) -> None:
    # name nel contenuto diverso dalla cartella -> errore di validazione
    bad = "---\nname: altro\ndescription: valida\n---\n\ncorpo"
    with pytest.raises(ValueError):
        write_skill(tmp_path, "mio-skill", bad)


def test_skill_dir_confined(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        read_skill(tmp_path, "../evasione")
