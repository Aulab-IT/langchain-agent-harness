from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

# Regola dello standard Agent Skills (agentskills.io) per il campo `name`:
# 1-64 caratteri, minuscole a-z e 0-9, trattini singoli, senza inizio/fine trattino.
_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_MAX_NAME = 64
_MAX_DESCRIPTION = 1024
_MAX_COMPATIBILITY = 500


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Separa il frontmatter YAML dal corpo Markdown di un SKILL.md."""
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    try:
        front = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        front = {}
    if not isinstance(front, dict):
        front = {}
    return front, parts[2].lstrip("\n")


def validate_skill(name: Any, dir_name: str, front: dict[str, Any]) -> list[str]:
    """Valida un SKILL.md contro lo standard Agent Skills. Ritorna la lista di errori."""
    errors: list[str] = []
    if not isinstance(name, str) or not name:
        errors.append("`name` mancante nel frontmatter.")
    else:
        if len(name) > _MAX_NAME:
            errors.append(f"`name` oltre {_MAX_NAME} caratteri.")
        if not _NAME_RE.match(name):
            errors.append(
                "`name` non valido: solo minuscole a-z, cifre e trattini singoli, "
                "senza trattino iniziale/finale o doppio."
            )
        if name != dir_name:
            errors.append(f"`name` ('{name}') deve coincidere con la cartella ('{dir_name}').")
    description = front.get("description")
    if not isinstance(description, str) or not description.strip():
        errors.append("`description` mancante o vuota.")
    elif len(description) > _MAX_DESCRIPTION:
        errors.append(f"`description` oltre {_MAX_DESCRIPTION} caratteri.")
    compatibility = front.get("compatibility")
    if isinstance(compatibility, str) and len(compatibility) > _MAX_COMPATIBILITY:
        errors.append(f"`compatibility` oltre {_MAX_COMPATIBILITY} caratteri.")
    return errors


def _skill_info(directory: Path) -> dict[str, Any]:
    skill_md = directory / "SKILL.md"
    front, body = parse_frontmatter(skill_md.read_text(encoding="utf-8"))
    errors = validate_skill(front.get("name"), directory.name, front)
    metadata = front.get("metadata")
    return {
        "name": directory.name,
        "declared_name": front.get("name"),
        "description": front.get("description") or "",
        "license": front.get("license"),
        "compatibility": front.get("compatibility"),
        "allowed_tools": front.get("allowed-tools") or front.get("allowed_tools"),
        "metadata": metadata if isinstance(metadata, dict) else {},
        "has_scripts": (directory / "scripts").is_dir(),
        "has_references": (directory / "references").is_dir(),
        "has_assets": (directory / "assets").is_dir(),
        "body_lines": len(body.splitlines()),
        "valid": not errors,
        "errors": errors,
    }


def list_skills(skills_dir: Path) -> list[dict[str, Any]]:
    if not skills_dir.exists():
        return []
    result: list[dict[str, Any]] = []
    for skill_md in sorted(skills_dir.glob("*/SKILL.md")):
        try:
            result.append(_skill_info(skill_md.parent))
        except OSError:
            continue
    return result


def confine_to_directory(base_dir: Path, relative_name: str) -> Path:
    """Risolve relative_name come figlio diretto di base_dir; ValueError se esce dalla directory."""
    base = base_dir.resolve()
    candidate = (base / relative_name).resolve()
    if candidate.parent != base:
        raise ValueError("Percorso non valido.")
    return candidate


def _skill_dir(skills_dir: Path, name: str) -> Path:
    """Cartella della skill, confinata in skills_dir (difesa oltre alla regex del name)."""
    if not _NAME_RE.match(name) or len(name) > _MAX_NAME:
        raise ValueError("Nome skill non valido.")
    return confine_to_directory(skills_dir, name)


def read_skill(skills_dir: Path, name: str) -> dict[str, Any]:
    directory = _skill_dir(skills_dir, name)
    skill_md = directory / "SKILL.md"
    if not skill_md.is_file():
        raise FileNotFoundError(name)
    info = _skill_info(directory)
    info["content"] = skill_md.read_text(encoding="utf-8")
    return info


def build_skill_md(name: str, description: str, body: str) -> str:
    return f"---\nname: {name}\ndescription: {description}\n---\n\n{body.strip()}\n"


def write_skill(skills_dir: Path, name: str, content: str) -> dict[str, Any]:
    """Scrive/aggiorna un SKILL.md dopo validazione contro lo standard."""
    directory = _skill_dir(skills_dir, name)
    front, _ = parse_frontmatter(content)
    errors = validate_skill(front.get("name", name), name, front)
    if errors:
        raise ValueError("; ".join(errors))
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "SKILL.md").write_text(content, encoding="utf-8")
    return read_skill(skills_dir, name)


def delete_skill(skills_dir: Path, name: str) -> None:
    directory = _skill_dir(skills_dir, name)
    if not directory.is_dir():
        raise FileNotFoundError(name)
    shutil.rmtree(directory)
