"""CRUD sicuro per subagent Markdown con frontmatter YAML."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from agent_harness.config import SUBAGENTS_LOCK

_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_MAX_NAME = 64
_MAX_DESCRIPTION = 1024
_MAX_PROMPT = 50_000
_TIERS = {"low", "mid", "high"}
_ROUTING_FIELDS = ("capabilities", "inputs", "outputs", "constraints")
_MAX_ROUTING_ITEMS = 50
_MAX_ROUTING_ITEM = 512


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    try:
        front = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        front = {}
    return (front if isinstance(front, dict) else {}), parts[2].lstrip("\n")


def _path(directory: Path, name: str) -> Path:
    if not isinstance(name, str) or not _NAME_RE.fullmatch(name) or len(name) > _MAX_NAME:
        raise ValueError("Nome subagent non valido.")
    root = directory.resolve()
    target = (root / f"{name}.md").resolve()
    if target.parent != root:
        raise ValueError("Percorso subagent non valido.")
    return target


def validate_subagent(spec: dict[str, Any], *, file_name: str | None = None) -> list[str]:
    errors: list[str] = []
    name = spec.get("name")
    if not isinstance(name, str) or not _NAME_RE.fullmatch(name) or len(name) > _MAX_NAME:
        errors.append("`name` non valido: kebab-case, massimo 64 caratteri.")
    elif file_name is not None and name != file_name:
        errors.append("`name` deve coincidere con il nome file.")
    description = spec.get("description")
    if not isinstance(description, str) or not description.strip():
        errors.append("`description` mancante o vuota.")
    elif len(description) > _MAX_DESCRIPTION:
        errors.append("`description` oltre 1024 caratteri.")
    tier = spec.get("model_tier", "low")
    if tier not in _TIERS:
        errors.append("`model_tier` deve essere low, mid o high.")
    tools = spec.get("tools", [])
    if not isinstance(tools, list) or not all(isinstance(tool, str) and tool for tool in tools):
        errors.append("`tools` deve essere una lista di stringhe.")
    for field_name in _ROUTING_FIELDS:
        values = spec.get(field_name, [])
        if not isinstance(values, list) or not all(
            isinstance(value, str) and value.strip() and len(value) <= _MAX_ROUTING_ITEM
            for value in values
        ):
            errors.append(
                f"`{field_name}` deve essere una lista di stringhe non vuote "
                f"(massimo {_MAX_ROUTING_ITEM} caratteri)."
            )
        elif len(values) > _MAX_ROUTING_ITEMS:
            errors.append(f"`{field_name}` può contenere al massimo {_MAX_ROUTING_ITEMS} voci.")
    if not isinstance(spec.get("read_only", False), bool):
        errors.append("`read_only` deve essere booleano.")
    prompt = spec.get("system_prompt", "")
    if not isinstance(prompt, str) or not prompt.strip():
        errors.append("System prompt mancante o vuoto.")
    elif len(prompt) > _MAX_PROMPT:
        errors.append("System prompt oltre 50000 caratteri.")
    return errors


def _read(path: Path) -> dict[str, Any]:
    front, prompt = parse_frontmatter(path.read_text(encoding="utf-8"))
    spec = {
        "name": front.get("name"),
        "description": front.get("description"),
        "model_tier": front.get("model_tier", "low"),
        "capabilities": front.get("capabilities", []),
        "inputs": front.get("inputs", []),
        "outputs": front.get("outputs", []),
        "constraints": front.get("constraints", []),
        "tools": front.get("tools", []),
        "read_only": front.get("read_only", False),
        "system_prompt": prompt,
    }
    errors = validate_subagent(spec, file_name=path.stem)
    return {
        **spec,
        "content": path.read_text(encoding="utf-8"),
        "valid": not errors,
        "errors": errors,
    }


def list_subagents(directory: Path) -> list[dict[str, Any]]:
    if not directory.exists():
        return []
    result: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.md")):
        try:
            result.append(_read(path))
        except OSError:
            continue
    return result


def read_subagent(directory: Path, name: str) -> dict[str, Any]:
    path = _path(directory, name)
    if not path.is_file():
        raise FileNotFoundError(name)
    return _read(path)


def build_subagent_md(spec: dict[str, Any]) -> str:
    front = {
        "name": spec["name"],
        "description": spec["description"],
        "model_tier": spec.get("model_tier", "low"),
        "capabilities": spec.get("capabilities", []),
        "inputs": spec.get("inputs", []),
        "outputs": spec.get("outputs", []),
        "constraints": spec.get("constraints", []),
        "tools": spec.get("tools", []),
        "read_only": spec.get("read_only", False),
    }
    yaml_front = yaml.safe_dump(front, allow_unicode=True, sort_keys=False).strip()
    return f"---\n{yaml_front}\n---\n\n{spec['system_prompt'].strip()}\n"


def write_subagent(directory: Path, spec: dict[str, Any]) -> dict[str, Any]:
    normalized = {
        **spec,
        "model_tier": spec.get("model_tier", "low"),
        "capabilities": spec.get("capabilities", []),
        "inputs": spec.get("inputs", []),
        "outputs": spec.get("outputs", []),
        "constraints": spec.get("constraints", []),
        "tools": spec.get("tools", []),
        "read_only": spec.get("read_only", False),
    }
    errors = validate_subagent(normalized)
    if errors:
        raise ValueError("; ".join(errors))
    path = _path(directory, str(normalized["name"]))
    content = build_subagent_md(normalized)
    with SUBAGENTS_LOCK:
        directory.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return read_subagent(directory, str(normalized["name"]))


def write_subagent_content(directory: Path, name: str, content: str) -> dict[str, Any]:
    _path(directory, name)
    front, prompt = parse_frontmatter(content)
    return write_subagent(
        directory, {**front, "system_prompt": prompt, "name": front.get("name", name)}
    )


def delete_subagent(directory: Path, name: str) -> None:
    path = _path(directory, name)
    with SUBAGENTS_LOCK:
        if not path.is_file():
            raise FileNotFoundError(name)
        path.unlink()


def load_subagent_specs(directory: Path) -> tuple[list[dict[str, Any]], list[str]]:
    specs: list[dict[str, Any]] = []
    warnings: list[str] = []
    for item in list_subagents(directory):
        if item["valid"]:
            specs.append(
                {
                    key: item[key]
                    for key in (
                        "name",
                        "description",
                        "model_tier",
                        "capabilities",
                        "inputs",
                        "outputs",
                        "constraints",
                        "tools",
                        "read_only",
                        "system_prompt",
                    )
                }
            )
        else:
            warnings.append(
                f"Subagent '{item['name'] or 'sconosciuto'}' ignorato: {'; '.join(item['errors'])}"
            )
    return specs, warnings
