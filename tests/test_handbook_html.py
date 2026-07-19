"""Test del generatore dell'artefatto navigabile.

La proprietà che conta: **gli snippet mostrati devono essere il codice vero**. Un
generatore che sbaglia di due righe produce una pagina credibile e falsa, cioè il
fallimento contro cui è stato costruito tutto il resto.

Il secondo test in ordine di importanza verifica che il codice spostato venga seguito:
l'artefatto risolve le ancore con `relocate`, non con i numeri scritti nel markdown, quindi
resta corretto anche prima di un `--write`.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str) -> ModuleType:
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"{name}_htmltest", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


gen = _load("handbook_html")
sync = gen.sync


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Un repo minimo con un manuale di una pagina e un file citato."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "esempio.py").write_text(
        "\n".join(
            [
                "import os",  # 1
                "",  # 2
                "def obiettivo():",  # 3
                "    marcatore_unico()",  # 4
                "    return 1",  # 5
            ]
        ),
        encoding="utf-8",
    )
    handbook = tmp_path / "docs" / "handbook"
    handbook.mkdir(parents=True)
    (handbook / "L1.md").write_text(
        "# L3 · Unità di prova\n\n"
        "**Unità:** stadio 1 → [1.1](../L2_UNITA.md#11--prova)\n\n"
        "Il comportamento vive in `esempio.py · L3–5`.\n",
        encoding="utf-8",
    )
    (tmp_path / "handbook.toml").write_text(
        'handbook = "docs/handbook"\n'
        'lockfile = "docs/handbook/anchors.lock.json"\n'
        'search_roots = ["src", "."]\n'
        'extensions = ["py"]\n'
        "\n[html]\nout = \"build/index.html\"\ncontext_lines = 1\n",
        encoding="utf-8",
    )
    return tmp_path


def _configure(repo: Path) -> object:
    cfg = sync.Config.load(repo / "handbook.toml")
    sync.use(cfg)
    sync.run("adopt", cfg)  # registra le impronte
    return cfg


def test_snippet_lines_are_the_real_file_lines(repo: Path) -> None:
    cfg = _configure(repo)
    _, snippets, _ = gen.collect(cfg)

    assert len(snippets) == 1
    snippet = snippets[0]
    source = (repo / snippet.file).read_text(encoding="utf-8").splitlines()
    expected = source[snippet.first - 1 : snippet.first - 1 + len(snippet.lines)]
    assert snippet.lines == expected


def test_moved_code_is_followed_without_rewriting_the_markdown(repo: Path) -> None:
    """La prova che l'artefatto usa `relocate` e non i numeri del markdown."""
    cfg = _configure(repo)

    target = repo / "src" / "esempio.py"
    target.write_text("# due\n# righe\n" + target.read_text(encoding="utf-8"), encoding="utf-8")

    _, snippets, counts = gen.collect(cfg)

    assert counts["relocated"] == 1, counts
    assert (snippets[0].start, snippets[0].end) == (5, 7)
    assert "marcatore_unico()" in "\n".join(snippets[0].lines)
    # Il markdown NON è stato riscritto: continua a dire L3–5.
    assert "L3–5" in (repo / "docs" / "handbook" / "L1.md").read_text(encoding="utf-8")


def test_unresolved_anchor_shows_a_badge_and_no_snippet(repo: Path) -> None:
    """Un'evidenza sparita non deve produrre righe plausibili."""
    cfg = _configure(repo)
    (repo / "src" / "esempio.py").write_text(
        "def altro():\n    niente()\n    pass\n    pass\n    pass\n", encoding="utf-8"
    )

    pages, snippets, counts = gen.collect(cfg)

    assert counts["lost"] == 1
    assert snippets == []
    assert "non risolta" in pages[0].html
    assert "<button class=\"anchor\"" not in pages[0].html


def test_page_model_carries_unit_and_stage(repo: Path) -> None:
    cfg = _configure(repo)
    pages, _, _ = gen.collect(cfg)
    assert pages[0].unit == "1.1"
    assert pages[0].stage == "stadio 1"
    assert pages[0].title == "L3 · Unità di prova"


def test_generated_page_is_self_contained(repo: Path) -> None:
    """Una CSP severa blocca CDN, font remoti e fetch: la pagina non deve chiederne."""
    cfg = _configure(repo)
    pages, snippets, counts = gen.collect(cfg)
    page = gen.build_page(cfg, pages, snippets, counts)

    # Si cerca la REGOLA, non la parola: il CSS contiene un commento che spiega perché
    # `@font-face` non si usa, e un test che non distingue le due cose è un test che
    # costringe a non scrivere commenti.
    assert re.search(r"@font-face\s*\{", page) is None
    assert re.search(r"""(?:src|href)\s*=\s*["']https?://""", page) is None
    assert "fetch(" not in page
    assert "cdn." not in page
    assert page.count("<script") == 2  # il modello e il comportamento, nient'altro


def test_model_json_cannot_break_out_of_its_script_tag(repo: Path) -> None:
    """Una pagina del manuale che contenga `</script>` non deve chiudere il tag."""
    cfg = _configure(repo)
    (repo / "docs" / "handbook" / "L1.md").write_text(
        "# Prova\n\nTesto con </script> dentro.\n", encoding="utf-8"
    )
    pages, snippets, counts = gen.collect(cfg)
    page = gen.build_page(cfg, pages, snippets, counts)

    body = re.search(r'id="model">(.*?)</script>', page, re.S)
    assert body is not None
    assert json.loads(body.group(1).replace("<\\/", "</"))


ASSETS = ROOT / "scripts" / "assets"


@pytest.mark.parametrize("asset", sorted(ASSETS.iterdir()), ids=lambda p: p.name)
def test_asset_has_no_invisible_control_characters(asset: Path) -> None:
    """Un NUL in un sorgente è invisibile e rompe i confronti senza errori.

    Successo davvero: `const MAP_SLUG = "\\x00mappa"` faceva fallire ogni `slug ===
    MAP_SLUG`, quindi la rotta della mappa non scattava mai — e il file *sembrava*
    corretto in ogni editor.
    """
    text = asset.read_text(encoding="utf-8")
    stray = {ch for ch in text if ord(ch) < 32 and ch not in "\n\t"}
    assert stray == set(), f"{asset.name} contiene {[hex(ord(c)) for c in stray]}"


def test_map_route_cannot_collide_with_a_real_page(repo: Path) -> None:
    """Lo slug della mappa non deve essere raggiungibile anche come pagina."""
    script = (ASSETS / "handbook.js").read_text(encoding="utf-8")
    match = re.search(r'const MAP_SLUG = "([^"]*)"', script)
    assert match is not None
    slug = match.group(1)
    assert slug and slug.strip() == slug

    cfg = _configure(repo)
    pages, _, _ = gen.collect(cfg)
    assert slug not in {page.slug for page in pages}


def test_huge_span_is_elided_in_the_middle(repo: Path) -> None:
    lines = [f"riga {n}" for n in range(1, 900)]
    snippet = gen.build_snippet(lines, 1, 899, context=0)
    assert snippet.elided > 0
    assert len(snippet.lines) == gen.MAX_SNIPPET_LINES + 1
    assert "righe omesse" in snippet.lines[gen.MAX_SNIPPET_LINES // 2]
