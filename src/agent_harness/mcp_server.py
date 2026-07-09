from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from agent_harness.config import Settings
from agent_harness.skills import (
    build_skill_md,
    install_skill,
    list_skills,
    read_skill,
    write_skill,
    write_skill_file,
)

mcp = FastMCP("harness-didattico")


def _skills_dir() -> Path:
    """Cartella skill host (fonte di verità): env override oppure Settings."""
    override = os.environ.get("HARNESS_SKILLS_DIR")
    if override:
        return Path(override).resolve()
    return Settings().skills_dir


def _sync_into_session(name: str) -> None:
    """Copia la skill appena mutata nella session_root del run attivo.

    La `SkillsMiddleware` di deepagents monta le skill dalla copia per-sessione: senza
    questa sincronizzazione una skill creata dall'agente esisterebbe su host ma non sarebbe
    leggibile nello stesso run. `HARNESS_SESSION_ROOT` è iniettato dalla factory.
    """
    session_root = os.environ.get("HARNESS_SESSION_ROOT")
    if not session_root:
        return
    source = _skills_dir() / name
    if not source.is_dir():
        return
    target = Path(session_root) / "skills" / name
    shutil.rmtree(target, ignore_errors=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target, symlinks=False)


def _brief(info: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": info.get("name"),
        "description": info.get("description"),
        "valid": info.get("valid"),
        "errors": info.get("errors"),
        "path": f"/skills/{info.get('name')}/SKILL.md",
    }


@mcp.tool()
def count_text(text: str) -> dict[str, int]:
    """Conta caratteri, parole e righe senza inviare il testo a servizi esterni."""
    return {
        "characters": len(text),
        "words": len(re.findall(r"\S+", text)),
        "lines": len(text.splitlines()),
    }


@mcp.tool()
def harness_glossary(term: str) -> str:
    """Restituisce una breve definizione locale di un termine dell'agent harness."""
    entries = {
        "harness": "Codice, configurazione ed esecuzione che trasformano un modello in agente.",
        "react": "Ciclo nel quale il modello ragiona, agisce con un tool e osserva il risultato.",
        "compaction": "Sintesi selettiva del contesto per proseguire senza superare la finestra.",
        "skill": "Procedura caricata su richiesta mediante progressive disclosure.",
        "checkpoint": "Snapshot dello stato LangGraph associato a un thread.",
    }
    return entries.get(term.casefold(), "Termine non presente nel glossario locale.")


@mcp.tool()
def skill_list() -> list[dict[str, Any]]:
    """Elenca le skill installate (nome, descrizione, validità) dalla cartella skill host."""
    return [_brief(info) for info in list_skills(_skills_dir())]


@mcp.tool()
def skill_read(name: str) -> dict[str, Any]:
    """Legge il SKILL.md completo di una skill installata."""
    info = read_skill(_skills_dir(), name)
    return {**_brief(info), "content": info.get("content")}


@mcp.tool()
def skill_create(name: str, description: str, body: str) -> dict[str, Any]:
    """Crea una nuova skill conforme allo standard Agent Skills e la rende usabile in questo run.

    `name`: minuscole a-z, cifre e trattini singoli (max 64), deve coincidere con la cartella.
    Scrive su host e sincronizza nella sessione attiva. Nota: la lista skill iniettata nel system
    prompt è caricata a inizio run, quindi per usarla subito leggi direttamente il path restituito.
    """
    content = build_skill_md(name, description, body)
    info = write_skill(_skills_dir(), name, content)
    _sync_into_session(name)
    return _brief(info)


@mcp.tool()
def skill_write_file(name: str, relpath: str, content: str) -> dict[str, Any]:
    """Aggiunge/aggiorna un file di risorsa in una skill (es. scripts/run.sh, references/x.md).

    `relpath` è confinato nella cartella della skill (niente `..` o percorsi assoluti).
    """
    result = write_skill_file(_skills_dir(), name, relpath, content)
    _sync_into_session(name)
    return {
        "name": name,
        "path": f"/skills/{name}/{relpath}",
        "written": True,
        "binary": result.get("binary", False),
    }


@mcp.tool()
def skill_install(
    source: str,
    value: str,
    ref: str | None = None,
    subdir: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Installa una skill da una fonte esterna e la rende usabile in questo run.

    `source`: "archive_url" (URL a .zip/.tar.gz), "git" (URL repo http/https, con `ref`/`subdir`
    opzionali) o "registry" (nome skill nel registry agentskills.io). L'archivio/repo viene
    estratto in modo blindato (no traversal/symlink/size-bomb) e validato contro lo standard.
    Ogni install è registrata nell'audit come effettuata dall'agente.
    """
    settings = Settings()
    info = install_skill(
        _skills_dir(),
        source,
        value,
        ref=ref,
        subdir=subdir,
        registry_url=settings.skills_registry_url,
        by="agent",
        force=force,
    )
    _sync_into_session(info["name"])
    return _brief(info)


if __name__ == "__main__":
    mcp.run(transport="stdio")
