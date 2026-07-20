"""Test del generatore della skill di navigazione.

La skill è ciò che un agente legge PRIMA di cercare nel codice. Se instrada male, fa
danno: manda a leggere la pagina sbagliata con la sicurezza di chi ha una mappa. I test
coprono l'instradamento — quali unità esistono, quali file toccano — non la prosa.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str) -> ModuleType:
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"{name}_skilltest", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


gen = _load("handbook_skill")
sync = gen.sync


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "alfa.py").write_text("\n".join(f"riga {n}" for n in range(1, 40)))
    (tmp_path / "src" / "beta.py").write_text("\n".join(f"riga {n}" for n in range(1, 40)))

    handbook = tmp_path / "docs" / "handbook"
    (handbook / "L3").mkdir(parents=True)
    (handbook / "L2_UNITA.md").write_text(
        "# L2 · Unità di comportamento\n\n"
        "## Stadio 1 · Ingresso\n\n"
        "### 1.1 · Prima unità\n\n"
        "> **Responsabilità.** Fare la cosa uno, senza\n"
        "> andare a capo male.\n\n"
        "| | |\n|---|---|\n| **Ingressi** | x |\n\n"
        "→ **[L3](L3/prima.md)**\n\n"
        "## Stadio trasversale · Governance\n\n"
        "### T.1 · Seconda unità\n\n"
        "> **Responsabilità.** Fare la cosa due.\n\n"
        "→ **[L3](L3/seconda.md)**\n",
        encoding="utf-8",
    )
    # `alfa.py` citato tre volte, `beta.py` una: l'ordine deve rifletterlo.
    (handbook / "L3" / "prima.md").write_text(
        "# L3 · Prima unità\n\n**Unità:** stadio 1 → [1.1](../L2_UNITA.md#11--prima)\n\n"
        "Vedi `alfa.py · L1–3`, `alfa.py · L5–7`, `alfa.py · L9–11` e `beta.py · L2–4`.\n",
        encoding="utf-8",
    )
    (handbook / "L3" / "seconda.md").write_text(
        "# L3 · Seconda unità\n\n**Unità:** trasversale → [T.1](../L2_UNITA.md#t1--seconda)\n\n"
        "Vedi `beta.py · L20–22`.\n",
        encoding="utf-8",
    )
    (tmp_path / "handbook.toml").write_text(
        'handbook = "docs/handbook"\n'
        'lockfile = "docs/handbook/anchors.lock.json"\n'
        'search_roots = ["src", "."]\n'
        'extensions = ["py"]\n',
        encoding="utf-8",
    )
    return tmp_path


def _configure(repo: Path) -> object:
    cfg = sync.Config.load(repo / "handbook.toml")
    sync.use(cfg)
    return cfg


def test_units_are_read_from_the_index_with_their_stage(repo: Path) -> None:
    units = gen.collect_units(_configure(repo))

    assert [u.id for u in units] == ["1.1", "T.1"]
    assert units[0].stage == "Stadio 1 · Ingresso"
    assert units[1].stage == "Stadio trasversale · Governance"
    assert units[0].page == "L3/prima.md"


def test_multiline_responsibility_becomes_one_clean_line(repo: Path) -> None:
    """Il blockquote va a capo con `>`: quei marcatori non devono finire nel testo."""
    units = gen.collect_units(_configure(repo))
    assert units[0].responsibility == "Fare la cosa uno, senza andare a capo male."
    assert ">" not in units[0].responsibility


def test_files_are_ordered_by_how_often_the_unit_cites_them(repo: Path) -> None:
    """L'elenco viene troncato: i siti principali devono stare in testa, non in ordine
    alfabetico — altrimenti finiscono nel taglio."""
    units = gen.collect_units(_configure(repo))
    assert units[0].files == ["src/alfa.py", "src/beta.py"]


def test_shared_files_section_names_the_units_that_meet_there(repo: Path) -> None:
    cfg = _configure(repo)
    body = gen.render(cfg, gen.collect_units(cfg), "manuale")

    assert "src/beta.py` → unità 1.1, T.1" in body
    # `alfa.py` lo cita una sola unità: non è un punto d'incontro.
    assert "src/alfa.py` → unità" not in body


def test_generated_skill_has_a_valid_frontmatter(repo: Path) -> None:
    cfg = _configure(repo)
    body = gen.render(cfg, gen.collect_units(cfg), "manuale")

    assert body.startswith("---\nname: manuale\ndescription: >-\n")
    assert body.count("---\n") >= 2


def test_the_skill_tells_the_agent_that_the_repository_is_authoritative(repo: Path) -> None:
    """È la regola che distingue una mappa da una fonte: senza, un agente si fida di
    una pagina che potrebbe descrivere codice cambiato."""
    cfg = _configure(repo)
    body = gen.render(cfg, gen.collect_units(cfg), "manuale")

    assert "la verità è il" in body
    assert "Verifica contro il codice" in body


def test_an_empty_handbook_fails_instead_of_writing_a_useless_skill(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    handbook = tmp_path / "docs" / "handbook"
    handbook.mkdir(parents=True)
    (handbook / "L2_UNITA.md").write_text("# L2 · Unità\n\nNiente ancora.\n", encoding="utf-8")
    (tmp_path / "handbook.toml").write_text(
        'handbook = "docs/handbook"\nsearch_roots = ["."]\nextensions = ["py"]\n',
        encoding="utf-8",
    )
    sync.use(sync.Config.load(tmp_path / "handbook.toml"))

    assert gen.main([]) == 1
    assert "Nessuna unità" in capsys.readouterr().out


def test_real_handbook_produces_every_unit() -> None:
    """Sul manuale vero: tutte le unità instradate, nessuna persa dal parsing."""
    cfg = sync.Config.discover(ROOT)
    sync.use(cfg)
    units = gen.collect_units(cfg)

    pages = {p.name for p in (cfg.handbook / "L3").glob("*.md")}
    routed = {Path(u.page).name for u in units}
    assert pages - routed == set(), f"unità non instradate: {pages - routed}"
    assert all(u.responsibility for u in units)
    assert all(u.files for u in units)
