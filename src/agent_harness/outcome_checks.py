"""Guardie deterministiche sugli outcome che non possono essere provati dal testo finale."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from agent_harness.skills import list_skills

_SKILL_ACTION = re.compile(
    r"\b(crea(?:re)?|aggiung(?:i|ere)|install(?:a|are)|aggiorn(?:a|are)|modific(?:a|are)|"
    r"create|add|install|update|modify)\b",
    re.IGNORECASE,
)
_SKILL_WORD = re.compile(r"\bskills?\b", re.IGNORECASE)
_CONDITIONAL_SKILL_ACTION = re.compile(
    r"\b(?:se|if|qualora)\b.{0,160}\b(?:non|no|not|nessun[ao]?)\b.{0,160}\bskills?\b",
    re.IGNORECASE | re.DOTALL,
)
_REUSE_MARKER = re.compile(
    r"\[SKILL_CATALOG_OUTCOME\s*=\s*reuse:([a-z0-9]+(?:-[a-z0-9]+)*)\]",
    re.IGNORECASE,
)


def requires_skill_catalog_change(goal: str) -> bool:
    """True solo per richieste esplicite di creazione/install/update di una skill."""
    return bool(_SKILL_WORD.search(goal) and _SKILL_ACTION.search(goal))


def allows_existing_skill_outcome(goal: str) -> bool:
    """Riconosce richieste condizionali: riuso valido oppure pubblicazione."""
    return bool(_CONDITIONAL_SKILL_ACTION.search(goal))


def _message_text(messages: list[Any]) -> str:
    for message in reversed(messages):
        role = getattr(message, "type", None) or getattr(message, "role", None)
        if isinstance(message, dict):
            role = message.get("role")
        if role not in {"ai", "assistant"}:
            continue
        content = getattr(message, "content", message)
        if isinstance(message, dict):
            content = message.get("content", "")
        if isinstance(content, str):
            return content
        elif isinstance(content, list):
            return "\n".join(
                str(block.get("text", ""))
                for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            )
    return ""


def skill_catalog_snapshot(skills_dir: Path) -> dict[str, str]:
    """Fingerprint di ogni skill valida visibile tramite stesso catalogo di `skill_list`."""
    valid_names = {item["name"] for item in list_skills(skills_dir) if item.get("valid")}
    snapshot: dict[str, str] = {}
    for name in sorted(valid_names):
        directory = skills_dir / name
        digest = hashlib.sha256()
        for path in sorted(directory.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            digest.update(path.relative_to(directory).as_posix().encode())
            digest.update(path.read_bytes())
        snapshot[name] = digest.hexdigest()
    return snapshot


class SkillCatalogCompletionCheck:
    """Richiede pubblicazione reale nel catalogo, non una bozza dentro `/workspace`."""

    def __init__(self, skills_dir: Path, baseline: dict[str, str]) -> None:
        self.skills_dir = skills_dir
        self.baseline = dict(baseline)
        self.inspected_skills: set[str] = set()

    def observe_event(self, event: dict[str, Any]) -> None:
        """Registra solo skill lette con successo; la dichiarazione finale da sola non basta."""
        if event.get("type") not in {"tool.completed", "subagent.tool.completed"}:
            return
        if event.get("tool") != "skill_read":
            return
        output = event.get("output")
        if not isinstance(output, str):
            return
        try:
            parsed = json.loads(output)
        except (json.JSONDecodeError, TypeError):
            parsed = None
        if isinstance(parsed, dict) and parsed.get("valid") is True:
            name = parsed.get("name")
            if isinstance(name, str):
                self.inspected_skills.add(name)
                return
        match = re.search(r'"name"\s*:\s*"([a-z0-9]+(?:-[a-z0-9]+)*)"', output)
        if match and '"valid": true' in output.lower():
            self.inspected_skills.add(match.group(1))

    def __call__(self, goal: str, messages: list[Any]) -> tuple[bool, str]:
        if not requires_skill_catalog_change(goal):
            return True, ""
        current = skill_catalog_snapshot(self.skills_dir)
        changed = sorted(
            name for name, fingerprint in current.items() if self.baseline.get(name) != fingerprint
        )
        if changed:
            return True, ""
        if allows_existing_skill_outcome(goal):
            match = _REUSE_MARKER.search(_message_text(messages))
            valid_names = {
                item["name"] for item in list_skills(self.skills_dir) if item.get("valid")
            }
            if (
                match
                and match.group(1) in valid_names
                and match.group(1) in self.inspected_skills
            ):
                return True, ""
            return (
                False,
                "Richiesta skill condizionale non risolta. Pubblica la nuova skill oppure, se "
                "una skill esistente è adeguata, leggila con skill_read e termina indicando "
                "[SKILL_CATALOG_OUTCOME=reuse:nome-skill] con evidenze della valutazione.",
            )
        return (
            False,
            "Skill non pubblicata nel catalogo. Usa skill_create, skill_write_file o "
            "skill_install; verifica frontmatter e presenza con skill_list. Un file creato "
            "solo in /workspace è una bozza, non una skill installata.",
        )


__all__ = [
    "SkillCatalogCompletionCheck",
    "allows_existing_skill_outcome",
    "requires_skill_catalog_change",
    "skill_catalog_snapshot",
]
