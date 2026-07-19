"""Test del renderer markdown del manuale.

Un renderer scritto a mano sbaglia sui casi che il contenuto reale contiene, non su quelli
inventati. Metà di questi test viene da costrutti presenti nelle pagine L3; l'altra metà
copre i modi in cui un renderer diventa una falla.

Il golden test finale rende tutti e 15 i file veri e verifica invarianti strutturali: non
confronta l'output byte per byte — sarebbe un test che fallisce a ogni virgola — ma
controlla che i conteggi tornino e che nessun `<` non escapato sopravviva.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
HANDBOOK = ROOT / "docs" / "handbook"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("mdlite", ROOT / "scripts" / "mdlite.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


md = _load()


# --- sicurezza ------------------------------------------------------------------------


def test_html_in_the_source_is_escaped_not_executed() -> None:
    out = md.render("Testo con <script>alert(1)</script> dentro.")
    assert "<script>" not in out
    assert "&lt;script&gt;" in out


def test_code_spans_keep_their_content_verbatim() -> None:
    """Un asterisco dentro il codice inline non è enfasi."""
    out = md.render("Vedi `a * b` e `<div>`.")
    assert "<code>a * b</code>" in out
    assert "<code>&lt;div&gt;</code>" in out
    assert "<em>" not in out


def test_link_becomes_an_anchor_with_a_quoted_href() -> None:
    out = md.render("Vedi [la pagina](L3/x.md#sezione).")
    assert '<a href="L3/x.md#sezione">la pagina</a>' in out


# --- costrutti presi dalle pagine reali -----------------------------------------------


def test_table_cell_containing_pipes_inside_code_is_not_split() -> None:
    """Il manuale documenta la chiave del lockfile, che contiene `|`."""
    source = "| Chiave | Ruolo |\n|---|---|\n| `doc|file|1-2` | identità |\n"
    out = md.render(source)
    assert out.count("<td>") == 2
    assert "doc|file|1-2" in out


def test_heading_slug_matches_the_github_style_links_used_in_the_handbook() -> None:
    assert md.slug("3.1 · Igiene dei blocchi-file verso il provider") == (
        "31--igiene-dei-blocchi-file-verso-il-provider"
    )
    assert md.slug("T.1 · Delega a subagenti") == "t1--delega-a-subagenti"


def test_blockquote_with_a_list_inside_is_rendered_as_such() -> None:
    """`lavoro-durevole.md` cita le due garanzie come lista dentro una citazione."""
    out = md.render("> - **prima**: cosa\n> - **seconda**: cosa\n")
    assert "<blockquote>" in out
    assert out.count("<li>") == 2
    assert "<strong>prima</strong>" in out


def test_wrapped_list_item_stays_one_item() -> None:
    out = md.render("- prima riga della voce\n  continuazione della stessa voce\n- seconda\n")
    assert out.count("<li>") == 2
    assert "prima riga della voce continuazione" in out


def test_fenced_block_keeps_indentation_and_escapes() -> None:
    out = md.render("```python\nif x < 1:\n    return None\n```")
    assert 'class="language-python"' in out
    assert "if x &lt; 1:\n    return None" in out


def test_paragraph_stops_at_a_table() -> None:
    out = md.render("Testo introduttivo\n| A | B |\n|---|---|\n| 1 | 2 |\n")
    assert out.index("<p>") < out.index("<table>")
    assert "|" not in out[out.index("<p>") : out.index("</p>")]


def test_horizontal_rule_is_not_a_heading() -> None:
    assert md.render("---") == "<hr>"


# --- golden: i 15 file veri ------------------------------------------------------------

PAGES = sorted((HANDBOOK / "L3").glob("*.md"))


def test_the_handbook_has_the_expected_pages() -> None:
    assert len(PAGES) >= 15


def _outside_fences(source: str) -> list[str]:
    """Le righe fuori dai blocchi recintati.

    Serve al contatore: `self-improvement.md` mostra codice Python commentato, e una riga
    `# Solo queste chiavi…` dentro un fence somiglia a un'intestazione senza esserlo. È
    il renderer ad avere ragione, non il conteggio ingenuo.
    """
    lines: list[str] = []
    inside = False
    for line in source.splitlines():
        if line.startswith("```"):
            inside = not inside
            continue
        if not inside:
            lines.append(line)
    return lines


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.name)
def test_real_page_renders_without_losing_structure(page: Path) -> None:
    source = page.read_text(encoding="utf-8")
    out = md.render(source)
    plain = _outside_fences(source)

    # Ogni intestazione del sorgente esiste nell'output.
    headings = len([ln for ln in plain if re.match(r"^#{1,4}\s", ln)])
    rendered = len(re.findall(r"<h[1-4] ", out))
    assert rendered == headings, f"{page.name}: {headings} intestazioni, {rendered} rese"

    # Ogni tabella del sorgente esiste nell'output.
    separators = len([ln for ln in plain if re.match(r"^\s*\|\s*:?-{2,}", ln)])
    assert out.count("<table>") == separators, page.name

    # Nessun `<` non escapato fuori dai tag che abbiamo generato noi.
    stripped = re.sub(r"</?(?:h[1-4]|p|ul|ol|li|table|thead|tbody|tr|th|td|pre|code|"
                      r"strong|em|blockquote|hr|div|a)\b[^>]*>", "", out)
    assert "<" not in stripped, f"{page.name}: markup non riconosciuto o `<` non escapato"

    # Le due sezioni obbligatorie dello schema sopravvivono al rendering.
    assert "Riepilogo evidenza" in out
    assert "Note per chi modifica" in out
