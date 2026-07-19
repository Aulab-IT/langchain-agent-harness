"""Test della logica che riscrive i riferimenti del manuale.

Questo strumento modifica 499 ancore in automatico: una rilocalizzazione sbagliata
riscriverebbe il manuale con numeri plausibili e falsi, che è peggio di non riscriverlo.
I casi qui sotto coprono i modi in cui può sbagliare, non quelli in cui funziona.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load() -> ModuleType:
    """Carica lo script per percorso: `scripts/` non è un package importabile."""
    path = ROOT / "scripts" / "handbook_sync.py"
    spec = importlib.util.spec_from_file_location("handbook_sync", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Va registrato prima di eseguirlo: `@dataclass` risolve le annotazioni cercando il
    # modulo in `sys.modules`, e senza questa riga trova `None`.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


sync = _load()


def _anchor(start: int, end: int, tmp_path: Path) -> object:
    return sync.Anchor(
        doc=tmp_path / "doc.md",
        file=tmp_path / "codice.py",
        start=start,
        end=end,
        dash="–",
        span=(0, 0),
    )


# --- scelta dell'impronta -------------------------------------------------------------


def test_fingerprint_prefers_the_distinctive_line_over_the_first(tmp_path: Path) -> None:
    """`return None` compare ovunque: come impronta non identifica niente."""
    lines = [
        "def alfa():",
        "    return None",
        "",
        "def beta():",
        "    # questo commento esiste una volta sola",
        "    return None",
    ]
    print_ = sync.fingerprint(lines, _anchor(5, 6, tmp_path))
    assert print_.head == "# questo commento esiste una volta sola"
    assert print_.head_offset == 0


def test_fingerprint_skips_a_repeated_head_in_favour_of_a_unique_one(tmp_path: Path) -> None:
    lines = ["    )", "    )", "    unico_marcatore()", "    )", "    )"]
    print_ = sync.fingerprint(lines, _anchor(1, 3, tmp_path))
    assert print_.head == "unico_marcatore()"
    assert print_.head_offset == 2  # la testa è due righe sotto l'inizio del range


def test_fingerprint_prefers_the_border_when_two_lines_are_equally_unique(
    tmp_path: Path,
) -> None:
    """A parità di unicità vince la riga più vicina al bordo: offset piccolo, meno fragile."""
    lines = ["    alfa()", "    beta()", "    gamma()"]
    print_ = sync.fingerprint(lines, _anchor(1, 3, tmp_path))
    assert print_.head == "alfa()"
    assert print_.head_offset == 0


def test_fingerprint_never_crosses_head_and_tail(tmp_path: Path) -> None:
    """Su un range di due righe i due insiemi di candidate si sovrappongono."""
    lines = ["riga unica alfa", "riga comune", "riga comune", "riga comune"]
    print_ = sync.fingerprint(lines, _anchor(1, 2, tmp_path))
    head_index = print_.head_offset
    tail_index = 1 - print_.tail_offset
    assert head_index <= tail_index


def test_fingerprint_rejects_an_empty_range(tmp_path: Path) -> None:
    """Un'ancora che punta a una riga vuota è sbagliata, non è codice sparito."""
    assert sync.fingerprint(["codice", "", "altro"], _anchor(2, 2, tmp_path)) is None


def test_fingerprint_rejects_a_range_past_the_end(tmp_path: Path) -> None:
    assert sync.fingerprint(["a", "b"], _anchor(1, 9, tmp_path)) is None


# --- rilocalizzazione -----------------------------------------------------------------


def test_relocation_follows_code_pushed_down(tmp_path: Path) -> None:
    before = ["import os", "", "def obiettivo():", "    corpo()", "    return 1"]
    anchor = _anchor(3, 5, tmp_path)
    print_ = sync.fingerprint(before, anchor)

    after = ["import os", "import sys", "", "# nuovo commento", "", *before[2:]]
    result = sync.relocate(after, anchor, print_)

    assert result.outcome == "relocated"
    assert (result.start, result.end) == (6, 8)


def test_unchanged_code_reports_ok(tmp_path: Path) -> None:
    lines = ["def obiettivo():", "    corpo()"]
    anchor = _anchor(1, 2, tmp_path)
    result = sync.relocate(lines, anchor, sync.fingerprint(lines, anchor))
    assert result.outcome == "ok"


def test_deleted_code_is_lost_not_guessed(tmp_path: Path) -> None:
    """Il caso che dà valore allo strumento: la pagina è da riscrivere, non da ricalcolare."""
    before = ["def sparita():", "    corpo_unico_da_cancellare()"]
    anchor = _anchor(1, 2, tmp_path)
    print_ = sync.fingerprint(before, anchor)

    result = sync.relocate(["def altra():", "    altro()"], anchor, print_)
    assert result.outcome == "lost"


def test_equidistant_duplicates_are_reported_not_picked(tmp_path: Path) -> None:
    """Meglio una riscrittura mancata che una sbagliata."""
    before = ["    marcatore()", "    coda()"]
    anchor = _anchor(1, 2, tmp_path)
    print_ = sync.fingerprint(before, anchor)

    # Due copie identiche a distanza uguale dalla posizione citata: non c'è modo di
    # sapere quale sia quella giusta, e sceglierne una a caso riscriverebbe il manuale
    # con un numero plausibile e falso.
    after = ["    marcatore()", "    coda()", "x", "y", "    marcatore()", "    coda()"]
    ambiguous = sync.relocate(after, _anchor(3, 4, tmp_path), print_)
    assert ambiguous.outcome == "ambiguous"


def test_nearest_match_wins_when_code_is_duplicated_far_away(tmp_path: Path) -> None:
    """Un blocco simile altrove nel file non deve dirottare l'ancora."""
    before = ["    marcatore()", "    coda()"]
    print_ = sync.fingerprint(before, _anchor(1, 2, tmp_path))

    after = ["    marcatore()", "    coda()", *["riempitivo"] * 40, "    marcatore()", "    coda()"]
    result = sync.relocate(after, _anchor(1, 2, tmp_path), print_)
    assert (result.start, result.end) == (1, 2)


# --- lettura delle ancore dal markdown ------------------------------------------------


def test_parses_inline_and_table_anchors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Le tabelle di riepilogo scrivono più range dopo un solo percorso."""
    code = tmp_path / "esempio.py"
    code.write_text("\n".join(f"riga {i}" for i in range(1, 60)), encoding="utf-8")
    doc = tmp_path / "pagina.md"
    doc.write_text(
        "Il comportamento vive in `esempio.py · L10–12`.\n"
        "| `esempio.py` | L20, L30–33 | ruolo |\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(sync, "SEARCH_ROOTS", (tmp_path,))

    ranges = [(a.start, a.end) for a in sync.parse_anchors(doc)]
    assert ranges == [(10, 12), (20, 20), (30, 33)]


def test_ignores_paths_that_do_not_resolve(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    doc = tmp_path / "pagina.md"
    doc.write_text("Vedi `inesistente.py · L1–2`.\n", encoding="utf-8")
    monkeypatch.setattr(sync, "SEARCH_ROOTS", (tmp_path,))
    assert sync.parse_anchors(doc) == []


# --- riscrittura ----------------------------------------------------------------------


def test_rewrite_preserves_the_dash_and_collapses_single_lines(tmp_path: Path) -> None:
    anchor = _anchor(5, 9, tmp_path)
    assert anchor.render(7, 11) == "L7–11"
    assert anchor.render(7, 7) == "L7"


def test_rewrite_applies_from_the_end_so_offsets_stay_valid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Due ancore sulla stessa riga: riscrivere la prima sposta la seconda."""
    code = tmp_path / "esempio.py"
    code.write_text("\n".join(f"riga {i}" for i in range(1, 200)), encoding="utf-8")
    doc = tmp_path / "pagina.md"
    doc.write_text("Vedi `esempio.py · L5` e `esempio.py · L9–10`.\n", encoding="utf-8")
    monkeypatch.setattr(sync, "SEARCH_ROOTS", (tmp_path,))

    first, second = sync.parse_anchors(doc)
    report = sync.Report(
        results=[
            sync.Result(first, "relocated", 100, 100),
            sync.Result(second, "relocated", 120, 121),
        ]
    )
    sync.rewrite_docs(report)

    assert doc.read_text(encoding="utf-8").strip() == (
        "Vedi `esempio.py · L100` e `esempio.py · L120–121`."
    )
