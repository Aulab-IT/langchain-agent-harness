import io
import tarfile
import zipfile
from pathlib import Path

import pytest

from agent_harness.skills import (
    build_skill_md,
    delete_skill,
    delete_skill_file,
    install_skill_from_archive,
    list_skill_files,
    list_skill_installs,
    list_skills,
    parse_frontmatter,
    read_skill,
    read_skill_file,
    validate_skill,
    write_skill,
    write_skill_file,
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


# --- File di risorsa (multi-file) ---


def _seed_skill(skills_dir: Path, name: str = "demo") -> None:
    content = build_skill_md(name, "Fa qualcosa. Usala quando serve.", "# Passi\n1. vai")
    write_skill(skills_dir, name, content)


def test_resource_file_roundtrip(tmp_path: Path) -> None:
    _seed_skill(tmp_path)
    write_skill_file(tmp_path, "demo", "scripts/run.sh", "echo ciao\n")
    write_skill_file(tmp_path, "demo", "references/note.md", "# nota")

    paths = {f["path"] for f in list_skill_files(tmp_path, "demo")}
    assert {"SKILL.md", "scripts/run.sh", "references/note.md"} <= paths
    assert read_skill_file(tmp_path, "demo", "scripts/run.sh")["content"] == "echo ciao\n"
    assert read_skill(tmp_path, "demo")["resource_count"] == 2

    delete_skill_file(tmp_path, "demo", "scripts/run.sh")
    remaining = {f["path"] for f in list_skill_files(tmp_path, "demo")}
    assert "scripts/run.sh" not in remaining


@pytest.mark.parametrize("relpath", ["../evil.sh", "/etc/passwd", "sub/../../out.txt"])
def test_resource_file_traversal_blocked(tmp_path: Path, relpath: str) -> None:
    _seed_skill(tmp_path)
    with pytest.raises(ValueError):
        write_skill_file(tmp_path, "demo", relpath, "x")


def test_delete_skill_md_via_file_api_blocked(tmp_path: Path) -> None:
    _seed_skill(tmp_path)
    with pytest.raises(ValueError):
        delete_skill_file(tmp_path, "demo", "SKILL.md")


# --- Install da archivio (sicurezza estrazione) ---


def _skill_zip(files: dict[str, str], *, symlink: str | None = None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for path, data in files.items():
            archive.writestr(path, data)
        if symlink:
            info = zipfile.ZipInfo(symlink)
            info.external_attr = (0o120000 | 0o777) << 16  # bit di symlink
            archive.writestr(info, "/etc/passwd")
    return buffer.getvalue()


def test_install_from_zip(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    data = _skill_zip(
        {
            "pkg/SKILL.md": "---\nname: fetched\ndescription: Skill importata.\n---\n\n# corpo",
            "pkg/scripts/go.sh": "echo go",
        }
    )
    info = install_skill_from_archive(skills_dir, data, "zip", value="test.zip")

    assert info["name"] == "fetched"
    assert info["valid"] is True
    assert (skills_dir / "fetched" / "scripts" / "go.sh").is_file()
    installs = list_skill_installs(skills_dir)
    assert installs and installs[-1]["name"] == "fetched"


def test_install_zip_slip_rejected(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    data = _skill_zip({"../evil.md": "boom", "pkg/SKILL.md": "---\nname: x\ndescription: y\n---\n"})
    with pytest.raises(ValueError):
        install_skill_from_archive(skills_dir, data, "zip")


def test_install_symlink_rejected(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    data = _skill_zip(
        {"pkg/SKILL.md": "---\nname: x\ndescription: y\n---\n"}, symlink="pkg/link"
    )
    with pytest.raises(ValueError):
        install_skill_from_archive(skills_dir, data, "zip")


def test_install_missing_skill_md_rejected(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    data = _skill_zip({"pkg/readme.txt": "niente skill qui"})
    with pytest.raises(ValueError):
        install_skill_from_archive(skills_dir, data, "zip")


def test_install_collision_requires_force(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    data = _skill_zip({"pkg/SKILL.md": "---\nname: dup\ndescription: prima versione ok.\n---\n"})
    install_skill_from_archive(skills_dir, data, "zip")
    with pytest.raises(FileExistsError):
        install_skill_from_archive(skills_dir, data, "zip")
    # con force sovrascrive senza errore
    info = install_skill_from_archive(skills_dir, data, "zip", force=True)
    assert info["name"] == "dup"


def test_install_tar_gz(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        payload = b"---\nname: tarred\ndescription: Da tarball di prova.\n---\n\n# c"
        info = tarfile.TarInfo("pkg/SKILL.md")
        info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))
    result = install_skill_from_archive(skills_dir, buffer.getvalue(), "tar.gz")
    assert result["name"] == "tarred"
