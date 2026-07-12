"""Tool «interni» dell'harness, in-process — l'equivalente locale del server MCP `local_harness`.

Questi tool (conta-testo, glossario, gestione skill) erano esposti via un server MCP stdio
avviato a parte. Ma un server stdio ha un costo pesante: ``langchain_mcp_adapters`` **spawna un
subprocess e lo interroga a ogni singola tool-call** (misurato ~1 s a chiamata, ~3,7 s solo per
elencarli all'avvio del run). Per tool che sono semplici funzioni Python locali è puro spreco.

Qui gli stessi tool girano **nello stesso processo dell'agente**: nessun fork, nessun re-import,
latenza sotto il millisecondo. Il valore didattico di MCP resta, e vive dove serve davvero: i
server MCP **esterni** (aggiunti dall'utente in ``state/mcp.json``) restano fuori processo, dove
l'isolamento conta. Il confine di sicurezza non cambia — questi tool toccano solo la cartella
skill e la copia di sessione, mai la shell host.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool, tool

from agent_harness.config import SKILLS_LOCK
from agent_harness.skills import (
    build_skill_md,
    install_skill,
    list_skills,
    read_skill,
    write_skill,
    write_skill_file,
)

_GLOSSARY: dict[str, str] = {
    "harness": "Codice, configurazione ed esecuzione che trasformano un modello in agente.",
    "react": "Ciclo nel quale il modello ragiona, agisce con un tool e osserva il risultato.",
    "compaction": "Sintesi selettiva del contesto per proseguire senza superare la finestra.",
    "skill": "Procedura caricata su richiesta mediante progressive disclosure.",
    "checkpoint": "Snapshot dello stato LangGraph associato a un thread.",
}


def _brief(info: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": info.get("name"),
        "description": info.get("description"),
        "valid": info.get("valid"),
        "errors": info.get("errors"),
        "path": f"/skills/{info.get('name')}/SKILL.md",
    }


def build_builtin_tools(
    skills_dir: Path, session_root: Path, *, registry_url: str
) -> list[BaseTool]:
    """Costruisce i tool interni legati a una cartella skill e alla radice di sessione del run.

    ``session_root`` è la radice per-run: dopo aver mutato una skill sull'host, la si copia qui
    sotto ``skills/`` così la ``SkillsMiddleware`` la vede subito nello stesso run — la stessa
    sincronizzazione che faceva il server MCP, ma senza uscire dal processo.
    """

    def _sync_into_session(name: str) -> None:
        source = skills_dir / name
        if not source.is_dir():
            return
        target = session_root / "skills" / name
        with SKILLS_LOCK:
            shutil.rmtree(target, ignore_errors=True)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source, target, symlinks=False)

    @tool
    def count_text(text: str) -> dict[str, int]:
        """Conta caratteri, parole e righe senza inviare il testo a servizi esterni."""
        return {
            "characters": len(text),
            "words": len(re.findall(r"\S+", text)),
            "lines": len(text.splitlines()),
        }

    @tool
    def harness_glossary(term: str) -> str:
        """Restituisce una breve definizione locale di un termine dell'agent harness."""
        return _GLOSSARY.get(term.casefold(), "Termine non presente nel glossario locale.")

    @tool
    def skill_list() -> list[dict[str, Any]]:
        """Elenca le skill installate (nome, descrizione, validità) dalla cartella skill."""
        return [_brief(info) for info in list_skills(skills_dir)]

    @tool
    def skill_read(name: str) -> dict[str, Any]:
        """Legge il SKILL.md completo di una skill installata."""
        info = read_skill(skills_dir, name)
        return {**_brief(info), "content": info.get("content")}

    @tool
    def skill_create(name: str, description: str, body: str) -> dict[str, Any]:
        """Crea una nuova skill conforme allo standard Agent Skills e la rende usabile nel run.

        `name`: minuscole a-z, cifre e trattini singoli (max 64), deve coincidere con la
        cartella. Scrive su host e sincronizza nella sessione attiva. La lista skill iniettata
        nel system prompt è caricata a inizio run, quindi per usarla subito leggi il path
        restituito.
        """
        content = build_skill_md(name, description, body)
        info = write_skill(skills_dir, name, content)
        _sync_into_session(name)
        return _brief(info)

    @tool
    def skill_write_file(name: str, relpath: str, content: str) -> dict[str, Any]:
        """Aggiunge/aggiorna un file di risorsa in una skill (es. scripts/run.sh, references/x).

        `relpath` è confinato nella cartella della skill (niente `..` o percorsi assoluti).
        """
        result = write_skill_file(skills_dir, name, relpath, content)
        _sync_into_session(name)
        return {
            "name": name,
            "path": f"/skills/{name}/{relpath}",
            "written": True,
            "binary": result.get("binary", False),
        }

    @tool
    def skill_install(
        source: str,
        value: str,
        ref: str | None = None,
        subdir: str | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        """Installa una skill da una fonte esterna e la rende usabile in questo run.

        `source`: "archive_url" (URL a .zip/.tar.gz), "git" (URL repo http/https, con
        `ref`/`subdir` opzionali) o "registry" (nome skill nel registry agentskills.io).
        L'archivio/repo viene estratto in modo blindato (no traversal/symlink/size-bomb) e
        validato contro lo standard. Ogni install è registrata nell'audit come fatta dall'agente.
        """
        info = install_skill(
            skills_dir,
            source,
            value,
            ref=ref,
            subdir=subdir,
            registry_url=registry_url,
            by="agent",
            force=force,
        )
        _sync_into_session(info["name"])
        return _brief(info)

    return [
        count_text,
        harness_glossary,
        skill_list,
        skill_read,
        skill_create,
        skill_write_file,
        skill_install,
    ]


__all__ = ["build_builtin_tools"]
