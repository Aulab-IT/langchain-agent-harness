"""Guardia contro il rot delle ancore del Harness Handbook.

Il manuale in `docs/handbook/` vale solo se ogni riferimento `file · L120–140` punta
davvero a qualcosa. Le righe si spostano a ogni refactor: questo test non può verificare
che l'ancora indichi il codice *giusto*, ma verifica che il file esista e che
l'intervallo di righe stia dentro il file. Basta a intercettare i casi in cui un modulo
viene accorciato o rinominato e il manuale resta indietro.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HANDBOOK = ROOT / "docs" / "handbook"

# Copre entrambe le forme usate nel manuale:
#   inline   → `factory.py · L85–90`
#   tabella  → | `src/agent_harness/durable.py` | L42, L207–224 |
ANCHOR = re.compile(
    r"(?P<path>[\w./-]+\.(?:py|tsx|ts|md))"
    r"[`\s]*[·|][`\s]*"
    r"L(?P<start>\d+)(?:[–-](?P<end>\d+))?"
)

# I file citati per nome corto vivono qui.
SEARCH_ROOTS = (
    ROOT / "src" / "agent_harness",
    ROOT / "client" / "src",
    ROOT / "client" / "src" / "components" / "shared",
    ROOT,
)


def _resolve(path: str) -> Path | None:
    for root in SEARCH_ROOTS:
        candidate = root / path
        if candidate.is_file():
            return candidate
    return None


def _anchors() -> list[tuple[Path, int, str, int, int]]:
    found: list[tuple[Path, int, str, int, int]] = []
    for doc in sorted(HANDBOOK.rglob("*.md")):
        for lineno, line in enumerate(doc.read_text(encoding="utf-8").splitlines(), 1):
            for match in ANCHOR.finditer(line):
                start = int(match.group("start"))
                end = int(match.group("end") or start)
                found.append((doc, lineno, match.group("path"), start, end))
    return found


def test_handbook_exists() -> None:
    assert (HANDBOOK / "README.md").is_file()
    assert (HANDBOOK / "L1_SISTEMA.md").is_file()
    assert (HANDBOOK / "L2_UNITA.md").is_file()
    assert (HANDBOOK / "L3").is_dir()


def test_handbook_has_anchors() -> None:
    """Un manuale senza evidenza è prosa: se il regex non trova nulla, è rotto lui."""
    assert len(_anchors()) >= 20


@pytest.mark.parametrize(
    "doc,lineno,path,start,end",
    _anchors(),
    ids=lambda value: str(value) if not isinstance(value, Path) else value.name,
)
def test_anchor_points_inside_file(
    doc: Path, lineno: int, path: str, start: int, end: int
) -> None:
    target = _resolve(path)
    origin = f"{doc.relative_to(ROOT)}:{lineno}"
    assert target is not None, f"{origin} cita un file inesistente: {path}"

    total = len(target.read_text(encoding="utf-8").splitlines())
    assert start >= 1, f"{origin} cita una riga non valida: L{start}"
    assert start <= end, f"{origin} cita un intervallo invertito: L{start}–{end}"
    assert end <= total, (
        f"{origin} cita {path} · L{start}–{end} ma il file ha {total} righe. "
        "L'ancora è marcita: ricontrolla il codice e aggiorna il manuale."
    )
