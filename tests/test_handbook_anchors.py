"""Guardia contro il rot delle ancore del Harness Handbook.

Il manuale in `docs/handbook/` vale solo se ogni riferimento `file · L120–140` punta
davvero a qualcosa. Le righe si spostano a ogni refactor: questo test non può verificare
che l'ancora indichi il codice *giusto* — per quello serve `handbook_sync --check`, che
confronta le impronte di contenuto — ma verifica che il range esista dentro il file.

Le ancore si leggono con `parse_anchors` dello script di sync, non con un regex locale.
Prima ce n'erano due, leggermente diversi: quello del test richiedeva un separatore `·` o
`|` e quindi non vedeva parte delle ancore che lo script invece riscriveva. Un guardiano
che guarda meno cose di quelle che il sorvegliato tocca non è un guardiano.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
HANDBOOK = ROOT / "docs" / "handbook"


def _load() -> ModuleType:
    """Carica lo script per percorso: `scripts/` non è un package importabile."""
    path = ROOT / "scripts" / "handbook_sync.py"
    spec = importlib.util.spec_from_file_location("handbook_sync_anchors", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


sync = _load()
CONFIG = sync.Config.discover(ROOT)


def _anchors() -> list[object]:
    return sync.all_anchors(CONFIG)


def test_handbook_exists() -> None:
    assert (HANDBOOK / "README.md").is_file()
    assert (HANDBOOK / "L1_SISTEMA.md").is_file()
    assert (HANDBOOK / "L2_UNITA.md").is_file()
    assert (HANDBOOK / "L3").is_dir()


def test_handbook_has_anchors() -> None:
    """Un manuale senza evidenza è prosa: se non ne trova nessuna, è rotto il lettore."""
    assert len(_anchors()) >= 500


def test_every_unit_is_linked_from_the_index() -> None:
    """Una pagina L3 che nessuno linka è una pagina che nessuno trova."""
    pages = {path.name for path in (HANDBOOK / "L3").glob("*.md")}
    linked = set()
    for index in (HANDBOOK / "README.md", HANDBOOK / "L2_UNITA.md"):
        text = index.read_text(encoding="utf-8")
        linked |= {name for name in pages if f"L3/{name}" in text}
    assert pages - linked == set()


@pytest.mark.parametrize(
    "anchor",
    _anchors(),
    ids=lambda a: f"{a.doc.name}:{a.file.name}:{a.start}-{a.end}",
)
def test_anchor_points_inside_file(anchor: object) -> None:
    total = len(anchor.file.read_text(encoding="utf-8").splitlines())  # type: ignore[attr-defined]
    origin = f"{anchor.doc.relative_to(ROOT)}"  # type: ignore[attr-defined]
    start: int = anchor.start  # type: ignore[attr-defined]
    end: int = anchor.end  # type: ignore[attr-defined]

    assert start >= 1, f"{origin} cita una riga non valida: L{start}"
    assert start <= end, f"{origin} cita un intervallo invertito: L{start}–{end}"
    assert end <= total, (
        f"{origin} cita {anchor.file.name} · L{start}–{end} ma il file ha "  # type: ignore[attr-defined]
        f"{total} righe. L'ancora è marcita: ricontrolla il codice e aggiorna il manuale."
    )
